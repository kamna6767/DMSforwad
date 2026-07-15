"""
Per-user Telethon client management and mass campaign logic.

Performance changes vs original:
  - _CONCURRENCY raised from 15 → 50 (per-user concurrent sends)
  - asyncio.Queue worker pattern replaces semaphore+gather-all.
    Workers pull targets one at a time, so the event loop is never
    flooded with thousands of coroutines at once.
  - DB writes are batched every DB_BATCH sends (default 5) instead of
    after every single send, cutting DB overhead by 5×.
  - asyncio.sleep(0) yields between DB batches so other users' tasks
    (including /start handlers) can run without being starved.
"""
import asyncio
import logging
import os
import time
from telethon import TelegramClient
from telethon.tl.types import User, InputUserEmpty
from telethon.tl.functions.messages import (
    GetChatInviteImportersRequest,
    HideChatJoinRequestRequest,
    CheckChatInviteRequest,
)
from telethon.errors import FloodWaitError, SessionPasswordNeededError, UserPrivacyRestrictedError

from config import API_ID, API_HASH, SESSIONS_DIR
import database as db

logger = logging.getLogger(__name__)

_clients: dict[int, TelegramClient] = {}
_tasks: dict[int, asyncio.Task] = {}

# ── Tuning knobs ──────────────────────────────────────────────────────────────
# Number of concurrent sends per user campaign.
# 50 saturates Telegram's per-account rate limit nicely; go higher at your own risk.
_CONCURRENCY = 50

# Write stats to DB every N successful sends.
# Lower = more accurate live counter; higher = faster campaign.
_DB_BATCH = 5


def session_path(user_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"user_{user_id}")


def get_client(user_id: int):
    return _clients.get(user_id)


async def create_client(user_id: int) -> TelegramClient:
    client = TelegramClient(
        session_path(user_id), API_ID, API_HASH,
        connection_retries=3,
        retry_delay=1,
        auto_reconnect=True,
    )
    await client.connect()
    _clients[user_id] = client
    return client


async def send_code(user_id: int, phone: str) -> str:
    client = await create_client(user_id)
    result = await client.send_code_request(phone)
    return result.phone_code_hash


async def sign_in(user_id: int, phone: str, code: str, phone_code_hash: str, password: str | None = None):
    client = _clients.get(user_id) or await create_client(user_id)
    try:
        user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        return user
    except SessionPasswordNeededError:
        if not password:
            raise
        user = await client.sign_in(password=password)
        return user


async def sign_in_2fa(user_id: int, password: str):
    client = _clients.get(user_id)
    if not client:
        raise RuntimeError("No client found")
    user = await client.sign_in(password=password)
    return user


async def load_existing_session(user_id: int) -> bool:
    """Load a Telethon session from disk if it exists. Non-blocking for other users."""
    path = session_path(user_id) + ".session"
    if not os.path.exists(path):
        return False
    if user_id in _clients:
        try:
            if await _clients[user_id].is_user_authorized():
                return True
        except Exception:
            pass
    try:
        client = await create_client(user_id)
        if await client.is_user_authorized():
            return True
        await client.disconnect()
        _clients.pop(user_id, None)
    except Exception:
        pass
    return False


async def disconnect_client(user_id: int):
    client = _clients.pop(user_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass


async def logout_user(user_id: int):
    client = _clients.get(user_id)
    if client:
        try:
            await client.log_out()
        except Exception:
            pass
    await disconnect_client(user_id)
    import glob
    for f in glob.glob(session_path(user_id) + "*"):
        try:
            os.remove(f)
        except Exception:
            pass


async def start_campaign(user_id: int, messages: list[dict], progress_cb, done_cb) -> bool:
    # Cancel any existing campaign for this user before starting a new one
    if user_id in _tasks and not _tasks[user_id].done():
        old_task = _tasks.pop(user_id)
        old_task.cancel()
        try:
            await old_task
        except (asyncio.CancelledError, Exception):
            pass
        import database as _db
        try:
            await _db.update_campaign(user_id, status="cancelled")
        except Exception:
            pass
    task = asyncio.create_task(
        _campaign_loop(user_id, messages, progress_cb, done_cb),
        name=f"campaign_{user_id}",
    )
    _tasks[user_id] = task
    return True


async def cancel_campaign(user_id: int):
    task = _tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _resolve_channel(client, channel_ref: str):
    """
    Resolve any channel reference to a Telethon entity.

    Handles both:
      • Public  — "@username", "username", or "https://t.me/username"
      • Private — "https://t.me/+HASH" or "https://t.me/joinchat/HASH"

    For private channels the account must already be a member / admin.
    """
    ref = channel_ref.strip()

    # ── Private invite link ────────────────────────────────────────────────
    invite_hash = None
    if "t.me/+" in ref:
        invite_hash = ref.split("t.me/+")[-1].rstrip("/").split("?")[0]
    elif "t.me/joinchat/" in ref:
        invite_hash = ref.split("t.me/joinchat/")[-1].rstrip("/").split("?")[0]

    if invite_hash:
        result = await client(CheckChatInviteRequest(hash=invite_hash))
        # ChatInviteAlready  → account is already a member; result.chat is the channel
        # ChatInvite         → not a member yet; result has limited info
        # Both have a `.chat` attribute with at least the channel id/access_hash
        return result.chat

    # ── Public username / numeric id ──────────────────────────────────────
    return await client.get_entity(ref)


async def get_pending_join_requests(user_id: int, channel: str) -> tuple[list, int]:
    """Return (importers[:200], total_count) — used only to show the count to the user."""
    client = _clients.get(user_id)
    if not client or not await client.is_user_authorized():
        raise RuntimeError("Not authorised. Please add your account first.")
    entity = await _resolve_channel(client, channel)
    result = await client(GetChatInviteImportersRequest(
        peer=entity,
        offset_date=None,
        offset_user=InputUserEmpty(),
        limit=200,
        requested=True,
    ))
    return result.importers, result.count


async def fetch_join_request_users(user_id: int, channel: str, limit: int) -> tuple[list, int]:
    """
    Fetch up to `limit` pending join-request User objects via pagination.

    Returns (users, total_count).
    Uses result.users (full User objects) so messages can be sent without
    a separate get_entity() call, which fails for users we've never met.
    """
    client = _clients.get(user_id)
    if not client or not await client.is_user_authorized():
        raise RuntimeError("Not authorised. Please add your account first.")
    entity = await _resolve_channel(client, channel)

    users = []
    total = 0
    offset_date = None
    offset_user = InputUserEmpty()
    batch_size = 200  # Telegram's max per request

    while len(users) < limit:
        fetch_n = min(batch_size, limit - len(users))
        result = await client(GetChatInviteImportersRequest(
            peer=entity,
            offset_date=offset_date,
            offset_user=offset_user,
            limit=fetch_n,
            requested=True,
        ))
        total = result.count
        if not result.importers:
            break

        # Build a map from user_id → User object for this batch
        user_map = {u.id: u for u in result.users}
        for imp in result.importers:
            u = user_map.get(imp.user_id)
            if u:
                users.append(u)

        last_imp = result.importers[-1]
        offset_date = last_imp.date
        last_user = user_map.get(last_imp.user_id)
        if last_user:
            from telethon.tl.types import InputUser
            offset_user = InputUser(user_id=last_user.id, access_hash=last_user.access_hash)
        else:
            break

        if len(result.importers) < fetch_n:
            break  # No more pages
        await asyncio.sleep(0.3)

    return users[:limit], total


async def accept_join_requests(user_id: int, channel: str, how_many: int) -> tuple[int, int]:
    client = _clients.get(user_id)
    if not client or not await client.is_user_authorized():
        raise RuntimeError("Not authorised. Please add your account first.")
    entity = await _resolve_channel(client, channel)
    result = await client(GetChatInviteImportersRequest(
        peer=entity,
        offset_date=None,
        offset_user=InputUserEmpty(),
        limit=max(how_many, 200),
        requested=True,
    ))
    total = result.count
    to_accept = result.importers[:how_many]
    accepted = 0
    for importer in to_accept:
        input_user = None
        try:
            input_user = await client.get_input_entity(importer.user_id)
            await client(HideChatJoinRequestRequest(
                peer=entity,
                user_id=input_user,
                approved=True,
            ))
            accepted += 1
            await asyncio.sleep(0.05)
        except FloodWaitError as fw:
            await asyncio.sleep(fw.seconds + 2)
            try:
                await client(HideChatJoinRequestRequest(peer=entity, user_id=input_user, approved=True))
                accepted += 1
            except Exception:
                pass
        except Exception as ex:
            logger.warning(f"Accept join request failed for {importer.user_id}: {ex}")
    return accepted, total


async def _send_message_item(client, entity, msg: dict, watermark_text: str = ""):
    """Send one message item (text or media) to entity.

    Honours two extra flags stored on the message dict:
      link_preview_disabled — if True, sends with no link-preview card.

    If watermark_text is provided it is appended to the text / caption.
    """
    no_preview = bool(msg.get("link_preview_disabled"))

    def _apply_wm(text: str) -> str:
        if not watermark_text:
            return text
        return (text.rstrip() + "\n\n" + watermark_text) if text else watermark_text

    if msg.get("media_path") and os.path.exists(msg["media_path"]):
        await client.send_file(
            entity,
            msg["media_path"],
            caption=_apply_wm(msg.get("content") or ""),
        )
    elif msg.get("content"):
        await client.send_message(
            entity,
            _apply_wm(msg["content"]),
            link_preview=not no_preview,
        )


async def _campaign_loop(user_id: int, messages: list[dict], progress_cb, done_cb):
    """
    Queue-based concurrent campaign loop.

    Architecture:
      1. All target users are put into an asyncio.Queue.
      2. _CONCURRENCY worker coroutines are spawned — each pulls one
         target at a time, sends the messages, then pulls the next.
      3. DB writes are batched every _DB_BATCH sends.
      4. After each DB batch we call asyncio.sleep(0) to yield back to
         the event loop so other users' /start commands and button
         presses are not starved.
    """
    client = _clients.get(user_id)
    if not client or not await client.is_user_authorized():
        # Session not in memory — try reloading from the saved session file.
        # This covers the common case where the bot was restarted and the
        # in-memory _clients dict was cleared, even though the session file
        # on disk is still valid.
        loaded = await load_existing_session(user_id)
        client = _clients.get(user_id)
        if not loaded or not client or not await client.is_user_authorized():
            await done_cb(user_id, "Not authorised. Please add your account first.")
            return

    is_premium = await db.check_premium_active(user_id)
    stats = await db.get_stats(user_id) or {}
    already_sent = stats.get("total_sent", 0)
    free_limit = await db.get_free_limit()
    limit = 999_999 if is_premium else max(0, free_limit - already_sent)

    # ── Watermark ──────────────────────────────────────────────────────────────
    wm_enabled = await db.get_watermark_enabled()
    wm_username = await db.get_watermark_username() if wm_enabled else ""
    watermark_text = f"This message was sent by @{wm_username}." if (wm_enabled and wm_username) else ""
    # ──────────────────────────────────────────────────────────────────────────

    try:
        dialogs = await client.get_dialogs(limit=None)
        me = await client.get_me()
        targets = [
            d.entity for d in dialogs
            if isinstance(d.entity, User)
            and not d.entity.bot
            and d.entity.id != me.id
        ]

        total = len(targets)
        await db.create_campaign(user_id)
        await db.update_campaign(user_id, total=total, sent=0, status="running")
        await progress_cb(user_id, 0, 0, total, None)

        queue: asyncio.Queue = asyncio.Queue()
        for t in targets:
            queue.put_nowait(t)

        sent_count = 0   # successfully sent (also used as atomic slot counter)
        failed_count = 0
        db_pending = 0
        stopped = False
        last_db_flush = time.monotonic()

        async def flush_db():
            nonlocal db_pending, last_db_flush
            if db_pending > 0:
                await db.increment_sent(user_id, db_pending)
                await db.update_campaign(user_id, sent=sent_count, status="running")
                db_pending = 0
                last_db_flush = time.monotonic()
                await asyncio.sleep(0)

        async def worker():
            nonlocal sent_count, failed_count, db_pending, stopped
            while True:
                try:
                    entity = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                if stopped:
                    queue.task_done()
                    break

                # ── Atomic slot reservation ────────────────────────────────────
                if sent_count >= limit:
                    stopped = True
                    queue.task_done()
                    break
                sent_count += 1           # slot reserved — no await above this line
                # ──────────────────────────────────────────────────────────────

                send_ok = False
                try:
                    for msg in messages:
                        await _send_message_item(client, entity, msg, watermark_text=watermark_text)
                    send_ok = True

                    db_pending += 1
                    label = (
                        getattr(entity, "username", None)
                        or getattr(entity, "first_name", None)
                        or str(entity.id)
                    )
                    await progress_cb(user_id, sent_count, failed_count, total, label)

                    if db_pending >= _DB_BATCH:
                        await flush_db()

                except FloodWaitError as fw:
                    logger.warning(f"FloodWait {fw.seconds}s for user {user_id}")
                    await flush_db()
                    await asyncio.sleep(fw.seconds + 1)
                    try:
                        for msg in messages:
                            await _send_message_item(client, entity, msg, watermark_text=watermark_text)
                        send_ok = True
                        db_pending += 1
                    except Exception:
                        failed_count += 1

                except UserPrivacyRestrictedError:
                    failed_count += 1

                except asyncio.CancelledError:
                    # Release the reserved slot so the final count stays accurate
                    sent_count -= 1
                    queue.task_done()
                    raise

                except Exception as ex:
                    logger.debug(f"Skip {entity.id}: {ex}")
                    failed_count += 1

                finally:
                    # If the send never actually succeeded, give the slot back
                    # so the free cap reflects real sends, not failed attempts.
                    if not send_ok:
                        sent_count -= 1
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(_CONCURRENCY)]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for w in workers:
                w.cancel()
            raise

        await flush_db()

        if not is_premium and sent_count >= limit:
            await done_cb(user_id, "free_limit")
        else:
            await db.update_campaign(user_id, status="done")
            await done_cb(user_id, None)

    except asyncio.CancelledError:
        await db.update_campaign(user_id, status="cancelled")
        raise
    except Exception as ex:
        logger.error(f"Campaign error for {user_id}: {ex}")
        await db.update_campaign(user_id, status="error")
        await done_cb(user_id, str(ex))
