"""
User-facing bot — fully advanced UI & features.
"""
import asyncio
import logging
import os
import secrets
import time
import warnings
from datetime import datetime, timezone
from io import BytesIO

warnings.filterwarnings("ignore", category=UserWarning)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import KeyboardButtonStyle
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

# ── Button colour helpers ──────────────────────────────────────────────────────
# GREEN  — positive actions: start, confirm, pay, join, retry
# RED    — destructive: stop, cancel, remove
# BLUE   — navigation / info: back, preview, stats, support
def _gbtn(text: str, **kw) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, style=KeyboardButtonStyle.SUCCESS, **kw)

def _rbtn(text: str, **kw) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, style=KeyboardButtonStyle.DANGER, **kw)

def _bbtn(text: str, **kw) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, style=KeyboardButtonStyle.PRIMARY, **kw)

import database as db
import userbot
import gmail_checker
from assets_data import get_image_bytes
from config import (
    BOT_TOKEN, UPI_ID, PLANS, BOT_USERNAME,
    ADMIN_USERNAME, FREE_DM_LIMIT, ADMIN_TG_ID, FREE_ACCEPT_LIMIT
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_progress_msg_ids: dict[int, int] = {}
_progress_last_edit: dict[int, float] = {}
_campaign_start_times: dict[int, float] = {}

# ── Plans cache (loaded from DB at startup, reloaded by admin bot after edits) ─
_PLANS_CACHE: dict = {k: dict(v) for k, v in PLANS.items()}


async def reload_plans():
    global _PLANS_CACHE
    _PLANS_CACHE = await db.get_plans()
    logger.info("Plans reloaded: %s", list(_PLANS_CACHE.keys()))

DIVIDER = "─" * 22


def _generate_order_id() -> str:
    """Return a short unique order ID like ORD-A1B2C3D4."""
    rand = secrets.token_hex(4).upper()
    return f"ORD-{rand}"


def _get_bot_image(name: str):
    """Return image bytes: custom DB-uploaded image first, then built-in fallback."""
    import os as _os
    path = _os.path.join("data", f"{name}_custom.jpg")
    if _os.path.exists(path):
        with open(path, "rb") as f:
            from io import BytesIO
            return BytesIO(f.read())
    return get_image_bytes(name)


async def _check_maintenance(update) -> bool:
    """Return True if maintenance mode is ON (and sends the user a notice)."""
    on = await db.get_maintenance_mode()
    if on:
        text = (
            "🔧 *Bot Under Maintenance*\n\n"
            "─────────────────────\n"
            "We're currently improving the bot for you.\n"
            "Please wait a moment and try again soon.\n\n"
            "📩 Contact admin for updates and support.\n"
            "─────────────────────\n\n"
            "_Thank you for your patience!_ 🙏"
        )
        try:
            await update.effective_message.reply_text(text, parse_mode="Markdown")
        except Exception:
            pass
        return True
    return False


def _build_progress_bar(sent: int, total: int, bar_len: int = 18) -> str:
    if total == 0:
        return "░" * bar_len
    filled = round(bar_len * sent / total)
    return "█" * filled + "░" * (bar_len - filled)


def _stop_kb():
    return InlineKeyboardMarkup([
        [_rbtn("⛔ Stop Campaign", callback_data="cb_stop_campaign")],
    ])


# ── Conversation states ───────────────────────────────────────────────────────
(
    ADD_PHONE, ADD_CODE, ADD_2FA,
    SET_MSG_COLLECT,
    PAY_UTR,
    GIFT_CODE_INPUT,
    PAY_UTR_AUTO,
    AP_CHANNEL_INPUT,
    AP_COUNT_INPUT,
    JD_CHANNEL_INPUT,
    JD_COUNT_INPUT,
    JD_MSG_INPUT,
    CAMP_CHANNEL_INPUT,
    CAMP_COUNT_INPUT,
    CP_PRICE_INPUT,
    CP_CHANNEL_INPUT,
    CP_MEMBER_COUNT,
    CP_UTR_INPUT,
) = range(18)


# ── Conversation-state registry ───────────────────────────────────────────────
# Populated in build_app(); used by _clear_user_convs to end stale conversations
# before a new flow starts, preventing state bleed-through across conversations.
_all_convs: list = []


async def _clear_user_convs(update: Update) -> None:
    """Erase every active ConversationHandler state for this user+chat.

    Call this at the top of every conversation entry-point so that tapping
    any button always starts that button's flow cleanly, regardless of what
    state the user may have been left in from a previous interaction.
    """
    uid = update.effective_user.id if update.effective_user else None
    cid = update.effective_chat.id if update.effective_chat else None
    if uid is None or cid is None:
        return
    key = (cid, uid)
    for conv in _all_convs:
        try:
            conv._conversations.pop(key, None)
        except Exception:
            pass


# ── Keyboards ─────────────────────────────────────────────────────────────────
# Cache of custom buttons added by admin — refreshed on startup and after admin changes
_EXTRA_BUTTONS: list = []


async def reload_custom_buttons():
    """Fetch custom buttons from DB and update the in-memory cache."""
    global _EXTRA_BUTTONS
    _EXTRA_BUTTONS = await db.get_custom_buttons()


def main_menu_kb():
    rows = [
        [_gbtn("🚀 Start Mass DM Campaign", callback_data="cb_campaign")],
        [_gbtn("📣 Channel Promo", callback_data="cb_channelpromo")],
        [_gbtn("✉️ Set Message", callback_data="cb_setmsg"),
         _bbtn("📋 Preview Message", callback_data="cb_previewmsg")],
        [_bbtn("📊 My Stats", callback_data="cb_stats"),
         _bbtn("👤 My Account", callback_data="cb_myaccount")],
        [_gbtn("👑 Go VIP Premium", callback_data="cb_premium"),
         _gbtn("🎁 Redeem Code", callback_data="cb_giftcode")],
        [_gbtn("➕ Add Account", callback_data="cb_addaccount"),
         _rbtn("➖ Remove Account", callback_data="cb_removeaccount")],
        [_gbtn("✅ Accept Pending", callback_data="cb_acceptpending"),
         _gbtn("👥 Join Request DM", callback_data="cb_joinrequestdm")],
        [_gbtn("🔗 Refer & Earn", callback_data="cb_refer")],
        [_bbtn("📖 How to Use", callback_data="cb_tutorial"),
         _bbtn("💬 Support", url="https://t.me/shubhxseller")],
    ]
    for btn in _EXTRA_BUTTONS:
        rows.append([_bbtn(btn["label"], url=btn["url"])])
    rows.append([InlineKeyboardButton(
        "🤖 Create Your Own Bot",
        url="https://t.me/shubhxseller?text=Hi%20Shubh%2C%20I%20want%20my%20own%20customized%20Auto%20DM%20bot.%20Let%27s%20discuss%20pricing%20and%20other%20details.",
    )])
    return InlineKeyboardMarkup(rows)


def premium_plans_kb():
    _ICONS = ["⚡", "🔥", "💎", "🏆", "👑", "🌟", "🔮", "✨", "💫", "⭐"]
    rows = []
    sorted_plans = sorted(_PLANS_CACHE.items(), key=lambda x: x[1].get("days", 0))
    for i, (key, plan) in enumerate(sorted_plans):
        icon = _ICONS[i % len(_ICONS)]
        rows.append([_gbtn(
            f"{icon} {plan['label']} — ₹{plan['price']}",
            callback_data=f"plan_{key}",
        )])
    rows.append([_bbtn("🔙 Back", callback_data="cb_back")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    return InlineKeyboardMarkup([[_bbtn("🔙 Back to Menu", callback_data="cb_back")]])


def done_kb(count: int = 0):
    label = f"✅ Done — {count} message(s) saved" if count else "✅ Done — Save & Finish"
    return InlineKeyboardMarkup([
        [_gbtn(label, callback_data="msg_done")],
        [_rbtn("🔙 Cancel", callback_data="cb_back")],
    ])


def paid_kb(plan_key):
    return InlineKeyboardMarkup([
        [_gbtn("✅ I've Paid — Submit UTR", callback_data=f"ipaid_{plan_key}")],
        [_bbtn("🔙 Choose Different Plan", callback_data="cb_premium")],
    ])


def payment_method_kb(plan_key):
    return InlineKeyboardMarkup([
        [_gbtn("👤 Admin Approval", callback_data=f"paymethod_admin_{plan_key}")],
        [_gbtn("⚡ Automatic Pay", callback_data=f"paymethod_auto_{plan_key}")],
        [_rbtn("🔙 Cancel", callback_data="cb_premium")],
    ])


def paid_auto_kb(plan_key):
    return InlineKeyboardMarkup([
        [_gbtn("✅ I've Paid — Submit UTR", callback_data=f"ipaid_auto_{plan_key}")],
        [_bbtn("🔙 Choose Different Plan", callback_data="cb_premium")],
    ])


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _premium_badge(user_id: int) -> str:
    is_active = await db.check_premium_active(user_id)
    if not is_active:
        return "🆓 Free Plan"
    prem = await db.get_premium(user_id)
    if prem:
        try:
            exp = datetime.fromisoformat(prem["expires_at"])
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            diff = (exp - now).days
            if diff <= 0:
                return "⚠️ Premium Expired"
            return f"👑 VIP Premium — {diff}d left"
        except Exception:
            return "👑 VIP Premium"
    return "👑 VIP Premium"


async def _support_url() -> str:
    handle = await db.get_setting("support_username", ADMIN_USERNAME)
    return f"https://t.me/{handle}"


# ── Guards ────────────────────────────────────────────────────────────────────
async def ensure_account(update: Update) -> bool:
    user_id = update.effective_user.id
    acc = await db.get_account(user_id)
    if acc:
        return True
    kb = InlineKeyboardMarkup([
        [_gbtn("➕ Add Account Now", callback_data="cb_addaccount")],
        [_bbtn("📖 How to Use", callback_data="cb_tutorial")],
    ])
    user = update.effective_user
    name = user.first_name or "there"
    msg = (
        f"🔐 *Account Not Linked, {name}!*\n\n"
        f"{DIVIDER}\n"
        f"⚡ This feature requires your Telegram account to be linked.\n\n"
        f"*How to link in 3 steps:*\n"
        f"1️⃣ Tap *Add Account Now* below\n"
        f"2️⃣ Enter your phone number with country code\n"
        f"   _(e.g. +91XXXXXXXXXX)_\n"
        f"3️⃣ Enter the OTP Telegram sends you\n\n"
        f"✅ Done! Takes less than 30 seconds.\n"
        f"{DIVIDER}\n"
        f"_Linking is safe and only used for sending DMs._"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return False


async def ensure_not_banned(update: Update) -> bool:
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if user and user.get("is_banned"):
        await update.effective_message.reply_text(
            "🚫 *You have been banned.*\n\n"
            "Contact support if you believe this is a mistake.",
            parse_mode="Markdown",
        )
        return False
    return True


# ── Force join ────────────────────────────────────────────────────────────────
def _is_private_link(ch: str) -> bool:
    """True when `ch` is a private Telegram invite link, not a public username."""
    return (
        ch.startswith("https://")
        or "joinchat" in ch
        or "t.me/+" in ch
        or "telegram.me/+" in ch
    )


async def _check_force_join(bot, user_id: int) -> list[dict]:
    """
    Return a list of channels the user still needs to join.
    Each entry is a dict:
        type    = "public" | "private"
        id      = username (public) or full link (private)
        url     = clickable join URL
        label   = button text shown to the user
    """
    channels = await db.get_force_join_channels()
    if not channels:
        return []

    # Fetch which private links this user has already confirmed (trust-based)
    confirmed_privates = await db.get_user_private_joins(user_id)

    pending = []
    for ch in channels:
        if _is_private_link(ch):
            # Private channel — we can't verify via Bot API; use trust-based tracking
            if ch not in confirmed_privates:
                pending.append({
                    "type": "private",
                    "id": ch,
                    "url": ch,
                    "label": "🔒 Join Private Channel",
                })
        else:
            # Public channel — verify membership via Bot API
            try:
                member = await bot.get_chat_member(f"@{ch}", user_id)
                if member.status in ("left", "kicked", "banned"):
                    pending.append({
                        "type": "public",
                        "id": ch,
                        "url": f"https://t.me/{ch}",
                        "label": f"📣 Join @{ch}",
                    })
            except Exception:
                # Bot not admin / channel unreachable — show join button anyway
                pending.append({
                    "type": "public",
                    "id": ch,
                    "url": f"https://t.me/{ch}",
                    "label": f"📣 Join @{ch}",
                })
    return pending


# ── /start ────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Always responds — every exception is caught so no user ever gets silence.
    """
    user = update.effective_user

    async def _do_start():
        # 1. Persist user (best-effort — never blocks the response)
        try:
            await db.upsert_user(user.id, username=user.username or "")
        except Exception as e:
            logger.warning("upsert_user failed for %s: %s", user.id, e)

        # 2. Maintenance gate
        try:
            if await _check_maintenance(update):
                return
        except Exception as e:
            logger.warning("maintenance check failed: %s", e)

        # 3. Referral deep-link
        if ctx.args:
            arg = ctx.args[0]
            if arg.startswith("ref_"):
                try:
                    referrer_id = int(arg[4:])
                    if referrer_id != user.id:
                        await db.set_referral(user.id, referrer_id)
                except Exception:
                    pass

        # 4. Ban check
        try:
            if not await ensure_not_banned(update):
                return
        except Exception as e:
            logger.warning("ban check failed: %s", e)

        # 5. Force-join check
        try:
            pending_channels = await _check_force_join(ctx.bot, user.id)
            if pending_channels:
                rows = [[_bbtn(ch["label"], url=ch["url"])] for ch in pending_channels]
                rows.append([_gbtn("✅ I've Joined All", callback_data="cb_check_joined")])
                await update.message.reply_text(
                    "📣 *Channel Membership Required*\n\n"
                    f"{DIVIDER}\n"
                    "You must join all channels below to use this bot.\n"
                    "After joining *every* channel, tap *I've Joined All*:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(rows),
                )
                return
        except Exception as e:
            logger.warning("force-join check failed: %s", e)

        # 6. Load session (best-effort)
        try:
            await userbot.load_existing_session(user.id)
        except Exception as e:
            logger.warning("load_existing_session failed for %s: %s", user.id, e)

        # 7. Build welcome text
        try:
            acc = await db.get_account(user.id)
            stats = await db.get_stats(user.id) or {}
            badge = await _premium_badge(user.id)
            custom_welcome = await db.get_setting("welcome_text", "")
        except Exception as e:
            logger.warning("DB reads in cmd_start failed: %s", e)
            acc, stats, badge, custom_welcome = None, {}, "🆓 Free", ""

        uname = f"@{user.username}" if user.username else "N/A"

        if acc:
            total_sent = stats.get("total_sent", 0)
            text = (
                f"👋 *Welcome back, {user.first_name}!*\n\n"
                f"{DIVIDER}\n"
                f"🆔 User ID: `{user.id}`\n"
                f"👤 Username: {uname}\n"
                f"📱 Account: `{acc['phone']}`\n"
                f"💎 Status: {badge}\n"
                f"📨 Total Sent: *{total_sent:,}* DMs\n"
                f"{DIVIDER}\n\n"
                "Choose an option below 👇"
            )
        elif custom_welcome:
            text = custom_welcome
        else:
            text = (
                f"🤖 *AUTO DMs BOT*\n\n"
                f"{DIVIDER}\n"
                f"🆔 Your ID: `{user.id}`\n"
                f"👤 Username: {uname}\n"
                f"{DIVIDER}\n\n"
                "🚀 *The fastest mass DM tool on Telegram*\n\n"
                "✅ Send to *ALL your DMs* at once\n"
                "⚡ Blazing-fast delivery\n"
                "🆓 Free plan: 100 sends\n"
                "👑 Premium: Unlimited sends\n\n"
                f"{DIVIDER}\n"
                "👇 Tap *Add Account* to get started!"
            )

        # 8. Send welcome (photo first, text fallback)
        try:
            await update.message.reply_photo(
                photo=_get_bot_image("welcome"), caption=text,
                parse_mode="Markdown", reply_markup=main_menu_kb(),
            )
        except Exception:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

    try:
        await _do_start()
    except Exception as e:
        logger.error("cmd_start unhandled error for %s: %s", user.id, e)
        # Guaranteed last-resort response
        try:
            await update.message.reply_text(
                f"👋 *Welcome!*\n\n{DIVIDER}\nUse the menu below to get started.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            pass


async def cb_check_joined(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Checking membership…")
    user = update.effective_user

    # Before re-checking: mark any currently-pending PRIVATE channels as confirmed
    # (trust-based — we can't verify private channel membership via Bot API)
    all_channels = await db.get_force_join_channels()
    confirmed_privates = await db.get_user_private_joins(user.id)
    for ch in all_channels:
        if _is_private_link(ch) and ch not in confirmed_privates:
            await db.mark_private_joined(user.id, ch)

    # Now re-run the full check (private channels should all be confirmed now)
    pending_channels = await _check_force_join(ctx.bot, user.id)
    if pending_channels:
        rows = [[_bbtn(ch["label"], url=ch["url"])] for ch in pending_channels]
        rows.append([_gbtn("✅ I've Joined All", callback_data="cb_check_joined")])
        await q.message.edit_text(
            "❌ *Still not all joined!*\n\n"
            "You haven't joined all required channels yet.\n"
            "Please join the ones below, then tap *I've Joined All* again:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    await userbot.load_existing_session(user.id)
    acc = await db.get_account(user.id)
    stats = await db.get_stats(user.id) or {}
    badge = await _premium_badge(user.id)
    custom_welcome = await db.get_setting("welcome_text", "")
    uname = f"@{user.username}" if user.username else "N/A"

    if acc:
        text = (
            f"👋 *Welcome back, {user.first_name}!*\n\n"
            f"{DIVIDER}\n"
            f"🆔 User ID: `{user.id}`\n"
            f"👤 Username: {uname}\n"
            f"📱 Account: `{acc['phone']}`\n"
            f"💎 Status: {badge}\n"
            f"📨 Total Sent: *{stats.get('total_sent', 0):,}* DMs\n"
            f"{DIVIDER}\n\nChoose an option below 👇"
        )
    elif custom_welcome:
        text = custom_welcome
    else:
        text = (
            f"✅ *All channels joined! Welcome, {user.first_name}!*\n\n"
            f"{DIVIDER}\n"
            f"🆔 Your ID: `{user.id}`\n"
            f"👤 Username: {uname}\n"
            f"{DIVIDER}\n\n"
            "👇 Tap *Add Account* to get started!"
        )

    await q.message.delete()
    try:
        await ctx.bot.send_photo(
            chat_id=user.id, photo=get_image_bytes("welcome"), caption=text,
            parse_mode="Markdown", reply_markup=main_menu_kb(),
        )
    except Exception:
        await ctx.bot.send_message(
            chat_id=user.id, text=text,
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )


# ── Back ──────────────────────────────────────────────────────────────────────
async def cb_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    acc = await db.get_account(user.id)
    badge = await _premium_badge(user.id)
    uname = f"@{user.username}" if user.username else "N/A"

    if acc:
        text = (
            f"🏠 *Main Menu*\n\n"
            f"{DIVIDER}\n"
            f"🆔 {user.id}  |  👤 {uname}\n"
            f"💎 {badge}\n"
            f"{DIVIDER}\n\nChoose an option 👇"
        )
    else:
        text = (
            f"🏠 *Main Menu*\n\n"
            f"{DIVIDER}\n"
            f"🆔 Your ID: `{user.id}`\n"
            f"{DIVIDER}\n\nChoose an option 👇"
        )
    try:
        await q.message.edit_caption(caption=text, parse_mode="Markdown", reply_markup=main_menu_kb())
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())


# ── My Account ────────────────────────────────────────────────────────────────
async def cb_myaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return
    user = update.effective_user
    user_id = user.id

    user_row = await db.get_user(user_id)
    acc = await db.get_account(user_id)
    prem = await db.get_premium(user_id)
    stats = await db.get_stats(user_id) or {}
    is_active = await db.check_premium_active(user_id)
    uname = f"@{user.username}" if user.username else "N/A"
    joined = str(user_row.get("created_at", "N/A"))[:10] if user_row else "N/A"

    if is_active and prem:
        try:
            exp = datetime.fromisoformat(prem["expires_at"])
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            diff = max(0, (exp - now).days)
            plan_status = f"👑 *VIP Premium*\n   Plan: `{prem['plan_key']}`\n   Expires: `{prem['expires_at'][:10]}`\n   ⏳ {diff} day(s) remaining"
        except Exception:
            plan_status = "👑 *VIP Premium* (active)"
    else:
        used = stats.get("total_sent", 0)
        fl = await db.get_free_limit()
        remaining = max(0, fl - used)
        plan_status = f"🆓 *Free Plan*\n   Sends used: `{used}` / `{fl}`\n   Remaining: `{remaining}`"

    msg = (
        f"👤 *MY PROFILE*\n"
        f"{DIVIDER}\n"
        f"🆔 User ID: `{user_id}`\n"
        f"👤 Username: {uname}\n"
        f"📱 Phone: `{acc['phone'] if acc else 'Not linked'}`\n"
        f"📅 Joined: `{joined}`\n\n"
        f"💎 *PLAN STATUS*\n"
        f"{DIVIDER}\n"
        f"{plan_status}\n\n"
        f"📊 *STATISTICS*\n"
        f"{DIVIDER}\n"
        f"📨 Total DMs Sent: *{stats.get('total_sent', 0):,}*\n"
        f"💰 Plans Purchased: *{stats.get('plans_bought', 0)}*\n"
    )
    await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=back_kb())


# ── My Stats ──────────────────────────────────────────────────────────────────
async def cb_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return
    user_id = update.effective_user.id

    stats = await db.get_stats(user_id) or {}
    camp = await db.get_campaign(user_id)
    is_active = await db.check_premium_active(user_id)
    prem = await db.get_premium(user_id)

    total_sent = stats.get("total_sent", 0)
    plans = stats.get("plans_bought", 0)

    last_camp = "None yet"
    if camp:
        status_map = {"done": "✅ Completed", "running": "🔄 Running", "cancelled": "⛔ Stopped", "error": "❌ Error"}
        last_camp = f"{status_map.get(camp['status'], camp['status'])} — {camp['sent']}/{camp['total']} sent"

    if is_active and prem:
        try:
            exp = datetime.fromisoformat(prem["expires_at"])
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            diff = max(0, (exp - now).days)
            plan_line = f"👑 VIP Premium — {diff}d left"
        except Exception:
            plan_line = "👑 VIP Premium"
    else:
        used = total_sent
        _fl = await db.get_free_limit()
        plan_line = f"🆓 Free — {max(0, _fl - used)} sends left"

    msg = (
        f"📊 *YOUR STATISTICS*\n"
        f"{DIVIDER}\n"
        f"💎 Plan: {plan_line}\n\n"
        f"📨 *Sending*\n"
        f"   Total DMs Sent: *{total_sent:,}*\n"
        f"   Plans Purchased: *{plans}*\n\n"
        f"🎯 *Last Campaign*\n"
        f"   {last_camp}\n"
        f"{DIVIDER}\n"
        f"_Keep sending to grow your reach!_ 🚀"
    )
    await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=back_kb())


# ── Tutorial ──────────────────────────────────────────────────────────────────
async def cb_tutorial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    support = await db.get_setting("support_username", ADMIN_USERNAME)
    text = (
        f"📖 *HOW TO USE AUTO DMs BOT*\n"
        f"{DIVIDER}\n\n"
        f"*STEP 1 — Add Your Account*\n"
        f"Tap ➕ Add Account → Enter your phone with country code (e.g. +91XXXXXXXXXX) → Enter the OTP sent to your Telegram → Enter 2FA password if you have one.\n\n"
        f"*STEP 2 — Set Your Message*\n"
        f"Tap ✉️ Set Message → Send your text, link, or image. You can add multiple messages — they'll be sent one after another to every contact.\n\n"
        f"*STEP 3 — Launch Campaign*\n"
        f"Tap 🚀 Start Mass DM Campaign → The bot sends your message to all your DMs instantly. Watch the live progress bar!\n\n"
        f"{DIVIDER}\n"
        f"📦 *PLANS & PRICING*\n\n"
        f"🆓 Free: 100 sends total\n"
        f"⚡ 1 Day — ₹10 (unlimited)\n"
        f"🔥 3 Days — ₹30\n"
        f"💎 7 Days — ₹60\n"
        f"🏆 15 Days — ₹100\n"
        f"👑 1 Month — ₹190\n\n"
        f"{DIVIDER}\n"
        f"⚠️ *TERMS*\n\n"
        f"• Use responsibly — no spam or illegal content\n"
        f"• We are not responsible for account restrictions\n"
        f"• Premium plans are non-refundable\n"
        f"• By using this bot you agree to these terms\n\n"
        f"{DIVIDER}\n"
        f"💬 Support: @{support}"
    )
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())


# ── Preview Message ───────────────────────────────────────────────────────────
async def cb_previewmsg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return
    user_id = update.effective_user.id

    msgs = await db.get_user_messages(user_id)
    if not msgs:
        await q.message.reply_text(
            f"📋 *Message Preview*\n\n"
            f"{DIVIDER}\n"
            "❌ No messages set yet.\n\n"
            "Tap *Set Message* to compose your campaign message.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("✉️ Set Message Now", callback_data="cb_setmsg")],
                [_bbtn("🔙 Back", callback_data="cb_back")],
            ]),
        )
        return

    await q.message.reply_text(
        f"📋 *Campaign Messages Preview*\n"
        f"{DIVIDER}\n"
        f"You have *{len(msgs)}* message(s) ready to send:\n",
        parse_mode="Markdown",
    )
    for i, m in enumerate(msgs, 1):
        if m.get("media_path") and os.path.exists(m["media_path"]):
            try:
                with open(m["media_path"], "rb") as f:
                    caption = f"📸 *Message {i}*" + (f"\n_{m['content']}_" if m.get("content") else "")
                    await q.message.reply_photo(photo=f, caption=caption, parse_mode="Markdown")
            except Exception:
                await q.message.reply_text(f"📎 *Message {i}:* [media file]", parse_mode="Markdown")
        elif m.get("content"):
            await q.message.reply_text(
                f"💬 *Message {i}:*\n{m['content']}",
                parse_mode="Markdown",
            )

    await q.message.reply_text(
        f"{DIVIDER}\n"
        "These messages will be sent to *all your DMs*.\n"
        "Ready? 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_gbtn("🚀 Start Campaign Now", callback_data="cb_campaign")],
            [_gbtn("✉️ Change Messages", callback_data="cb_setmsg")],
            [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
        ]),
    )


# ── Premium ───────────────────────────────────────────────────────────────────
async def cb_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return
    user_id = update.effective_user.id
    is_active = await db.check_premium_active(user_id)
    prem = await db.get_premium(user_id)
    upi = await db.get_setting("upi_id", UPI_ID)

    if is_active and prem:
        try:
            exp = datetime.fromisoformat(prem["expires_at"])
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            diff = max(0, (exp - now).days)
            status_line = f"✅ Active — *{diff} day(s)* remaining (expires `{prem['expires_at'][:10]}`)"
        except Exception:
            status_line = "✅ *Premium Active*"
    else:
        used = (await db.get_stats(user_id) or {}).get("total_sent", 0)
        _fl2 = await db.get_free_limit()
        remaining = max(0, _fl2 - used)
        status_line = f"🆓 Free Plan — `{remaining}` sends remaining"

    text = (
        f"👑 *VIP PREMIUM*\n"
        f"{DIVIDER}\n"
        f"💎 Current Status: {status_line}\n"
        f"{DIVIDER}\n\n"
        f"🚀 *What Premium Unlocks:*\n"
        f"   ✅ Unlimited DM sends\n"
        f"   ⚡ Maximum speed\n"
        f"   🔥 Priority support\n"
        f"   📊 Full campaign analytics\n\n"
        f"{DIVIDER}\n"
        f"💳 Payment: *UPI* — `{upi}`\n"
        f"{DIVIDER}\n\n"
        f"Select a plan to continue 👇"
    )
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=premium_plans_kb())


async def cb_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    plan_key = q.data.replace("plan_", "")
    plan = _PLANS_CACHE.get(plan_key)
    if not plan:
        return

    text = (
        f"💳 *{plan['label']} — ₹{plan['price']}*\n"
        f"{DIVIDER}\n"
        f"💰 Amount: *₹{plan['price']}*\n"
        f"⏳ Duration: *{plan['days']} day(s)*\n"
        f"{DIVIDER}\n\n"
        f"Choose how you'd like to pay 👇\n\n"
        f"👤 *Admin Approval* — Pay and submit your UTR. Admin reviews and activates your plan manually.\n\n"
        f"⚡ *Automatic Pay* — Pay and submit your UTR. The bot verifies your FamPay payment automatically and activates instantly."
    )
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=payment_method_kb(plan_key))


async def _show_payment_qr(message, plan_key: str, plan: dict, upi: str, kb, order_id: str = ""):
    text = (
        f"💳 *PAYMENT — {plan['label']}*\n"
        f"{DIVIDER}\n"
        + (f"🪪 Order ID: `{order_id}`\n" if order_id else "")
        + f"💰 Amount: *₹{plan['price']}*\n"
        f"⏳ Duration: *{plan['days']} day(s)*\n"
        f"📲 UPI ID: `{upi}`\n"
        f"{DIVIDER}\n\n"
        f"*How to pay:*\n"
        f"1️⃣ Scan the QR *or* open any UPI app\n"
        f"2️⃣ Send ₹{plan['price']} to `{upi}`\n"
        f"3️⃣ Note your *UTR / Transaction ID*\n"
        f"4️⃣ Tap *I've Paid* and enter the UTR\n\n"
        + (f"_Keep your Order ID `{order_id}` handy for support._" if order_id else "")
    )
    # Build QR image: dynamic UPI QR first, then uploaded/built-in fallback
    qr_image = None
    if order_id and upi:
        try:
            import qr_utils
            qr_image = BytesIO(qr_utils.generate_upi_qr(upi, plan["price"], order_id))
        except Exception:
            pass
    if qr_image is None:
        try:
            qr_image = _get_bot_image("qr")
        except Exception:
            pass
    if qr_image is not None:
        try:
            await message.reply_photo(
                photo=qr_image, caption=text,
                parse_mode="Markdown", reply_markup=kb,
            )
            return
        except Exception:
            pass
    await message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_paymethod_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    plan_key = q.data.replace("paymethod_admin_", "")
    plan = _PLANS_CACHE.get(plan_key)
    if not plan:
        return
    upi = await db.get_setting("upi_id", UPI_ID)
    order_id = _generate_order_id()
    ctx.user_data["pending_order_id"] = order_id
    await _show_payment_qr(q.message, plan_key, plan, upi, paid_kb(plan_key), order_id=order_id)


async def cb_paymethod_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await ensure_account(update):
        return
    plan_key = q.data.replace("paymethod_auto_", "")
    plan = _PLANS_CACHE.get(plan_key)
    if not plan:
        return
    upi = await db.get_setting("upi_id", UPI_ID)
    order_id = _generate_order_id()
    ctx.user_data["auto_pending_order_id"] = order_id
    await _show_payment_qr(q.message, plan_key, plan, upi, paid_auto_kb(plan_key), order_id=order_id)


async def cb_ipaid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)
    plan_key = q.data.replace("ipaid_", "")
    ctx.user_data["pending_plan"] = plan_key
    plan = _PLANS_CACHE.get(plan_key, {})
    await q.message.reply_text(
        f"✅ *Great! Almost done.*\n\n"
        f"{DIVIDER}\n"
        f"Plan: *{plan.get('label', plan_key)}* — ₹{plan.get('price', '')}\n"
        f"{DIVIDER}\n\n"
        "Please enter your *UTR number* (Transaction ID).\n"
        "It's usually 12 digits and found in your payment receipt.",
        parse_mode="Markdown",
    )
    return PAY_UTR


async def handle_utr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text.strip()
    user_id = update.effective_user.id
    plan_key = ctx.user_data.get("pending_plan")
    order_id = ctx.user_data.pop("pending_order_id", "")
    plan = _PLANS_CACHE.get(plan_key, {})
    if not plan:
        await update.message.reply_text("⚠️ Session expired. Please select a plan again.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    payment = await db.create_payment(user_id, plan_key, plan["price"], order_id=order_id)
    await db.update_payment(payment["id"], utr=utr)

    user = update.effective_user
    uname = f"@{user.username}" if user.username else "N/A"
    if ADMIN_TG_ID:
        try:
            order_line = f"🪪 Order: `{order_id}`\n" if order_id else ""
            await ctx.bot.send_message(
                chat_id=ADMIN_TG_ID,
                text=(
                    f"🔔 *New Payment — Admin Approval*\n\n"
                    f"─────────────────────\n"
                    f"👤 User: `{user.id}` | {uname}\n"
                    f"📦 Plan: *{plan['label']}*\n"
                    f"💰 Amount: ₹{plan['price']}\n"
                    f"{order_line}"
                    f"🔖 UTR: `{utr}`\n"
                    f"─────────────────────\n\n"
                    f"Open your admin bot to approve or reject."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    support = await db.get_setting("support_username", ADMIN_USERNAME)
    order_line = f"🪪 Order ID: `{order_id}`\n" if order_id else ""
    await update.message.reply_text(
        f"🎉 *Payment Submitted!*\n\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan['label']}*\n"
        f"💰 Amount: ₹{plan['price']}\n"
        f"{order_line}"
        f"🔖 UTR: `{utr}`\n"
        f"⏳ Status: Pending Review\n"
        f"{DIVIDER}\n\n"
        f"The admin will review and approve your payment shortly.\n"
        f"You'll receive a notification the moment it's approved! 🚀\n\n"
        f"💬 Support: @{support}",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Auto Pay conversation ─────────────────────────────────────────────────────
async def cb_ipaid_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)
    plan_key = q.data.replace("ipaid_auto_", "")
    ctx.user_data["auto_pending_plan"] = plan_key
    plan = _PLANS_CACHE.get(plan_key, {})
    await q.message.reply_text(
        f"⚡ *Auto Payment Verification*\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan.get('label', plan_key)}* — ₹{plan.get('price', '')}\n"
        f"{DIVIDER}\n\n"
        "✅ *Step 1 done* — Payment QR scanned\n"
        "🔢 *Step 2* — Enter your *UTR / Transaction ID*\n\n"
        "📌 *Where to find it?*\n"
        "• GPay / PhonePe / Paytm — Payment receipt screen\n"
        "• Bank SMS — Look for 'UTR' or 'Ref No'\n"
        "• Any UPI app — Transaction details\n\n"
        "Type the UTR or Transaction ID below 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("❌ Cancel", callback_data="cb_back")],
        ]),
    )
    return PAY_UTR_AUTO


async def _do_autopay_verify(
    utr: str,
    plan_key: str,
    plan: dict,
    user_id: int,
    order_id: str,
    hold_msg,
    ctx,
    user,
    is_retry: bool = False,
):
    """Core verification logic shared by first attempt and retry."""
    result = await asyncio.get_running_loop().run_in_executor(
        None, gmail_checker.check_payment, utr, plan["price"]
    )

    if result.matched:
        await db.mark_utr_used(utr, user_id)
        await db.set_premium(user_id, plan_key, plan["days"])
        await db.increment_plans(user_id)
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await hold_msg.edit_text(
            f"🎉 *Payment Verified Successfully!*\n"
            f"{DIVIDER}\n"
            f"📦 Plan: *{plan['label']}*\n"
            f"💰 Amount Paid: ₹{plan['price']}\n"
            f"🔖 UTR: `{utr}`\n"
            f"⏳ Duration: *{plan['days']} day(s)*\n"
            f"🕐 Activated: Just now\n"
            f"{DIVIDER}\n\n"
            "🚀 *Premium is now ACTIVE!*\n"
            "You can now send unlimited DMs.\n\n"
            f"💬 Support: @{support}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return True

    # Verification failed — determine failure reason for tailored message
    reason = result.reason  # "not_found" | "amount_mismatch" | "gmail_not_configured" | "gmail_auth_error" | "error"

    if reason == "amount_mismatch":
        # Found the UTR but amount didn't match — likely wrong plan selected
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await hold_msg.edit_text(
            f"⚠️ *Amount Mismatch Detected*\n"
            f"{DIVIDER}\n"
            f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
            f"🔖 UTR: `{utr}`\n"
            f"{DIVIDER}\n\n"
            "✅ Your UTR was found in our inbox.\n"
            f"❌ However, the payment amount does *not match* ₹{plan['price']}.\n\n"
            "Please make sure you:\n"
            f"• Paid exactly ₹{plan['price']} for this plan\n"
            "• Selected the correct plan\n\n"
            f"Contact support if you believe this is a mistake.\n"
            f"💬 @{support}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
            ]),
        )
        return False

    if reason in ("gmail_not_configured", "gmail_auth_error"):
        # Admin hasn't set up Gmail — fall back to manual review
        payment = await db.create_payment(user_id, plan_key, plan["price"], order_id=order_id)
        await db.update_payment(payment["id"], utr=utr)
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await hold_msg.edit_text(
            f"🔔 *Submitted for Manual Review*\n"
            f"{DIVIDER}\n"
            f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
            f"🔖 UTR: `{utr}`\n"
            f"{DIVIDER}\n\n"
            "Auto-verification is currently unavailable.\n"
            "Your payment details have been sent to the admin for *manual approval*.\n\n"
            "⏱ *Typical approval time: 1–30 minutes*\n\n"
            f"💬 Contact support: @{support}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
            ]),
        )
        _notify_admin_failed(ctx, user, plan, utr, order_id, "Gmail not configured")
        return False

    # not_found or generic error — offer retry
    payment = await db.create_payment(user_id, plan_key, plan["price"], order_id=order_id)
    await db.update_payment(payment["id"], utr=utr)
    support = await db.get_setting("support_username", ADMIN_USERNAME)
    retry_label = "🔄 Retry Verification" if not is_retry else "🔄 Try Again"
    await hold_msg.edit_text(
        f"❌ *Payment Not Found*\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
        f"🔖 UTR Entered: `{utr}`\n"
        f"{DIVIDER}\n\n"
        "We couldn't find this payment in our inbox.\n\n"
        "📋 *Please check:*\n"
        "• The UTR / Transaction ID is correct\n"
        "• The payment was sent to the correct UPI ID\n"
        f"• The amount is exactly ₹{plan['price']}\n\n"
        "_Payments sometimes take 1–2 minutes to appear._\n"
        "Tap *Retry* after a moment, or contact support.\n\n"
        f"💬 Support: @{support}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_gbtn(retry_label, callback_data=f"autopay_retry_{plan_key}|{utr}")],
            [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
        ]),
    )
    _notify_admin_failed(ctx, user, plan, utr, order_id, "Not found in Gmail")
    return False


def _notify_admin_failed(ctx, user, plan: dict, utr: str, order_id: str, reason: str):
    """Fire-and-forget admin notification on auto-verify failure."""
    async def _send():
        if not ADMIN_TG_ID:
            return
        try:
            uname = f"@{user.username}" if user.username else "N/A"
            order_line = f"🪪 Order: `{order_id}`\n" if order_id else ""
            await ctx.bot.send_message(
                chat_id=ADMIN_TG_ID,
                text=(
                    f"🔔 *Auto-Verify Failed*\n\n"
                    f"{DIVIDER}\n"
                    f"👤 User: `{user.id}` | {uname}\n"
                    f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
                    f"{order_line}"
                    f"🔖 UTR: `{utr}`\n"
                    f"❗ Reason: {reason}\n"
                    f"{DIVIDER}\n\n"
                    "Check your admin bot to approve or reject."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
    asyncio.create_task(_send())


async def handle_utr_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text.strip()
    user_id = update.effective_user.id
    plan_key = ctx.user_data.get("auto_pending_plan")
    order_id = ctx.user_data.pop("auto_pending_order_id", "")
    plan = _PLANS_CACHE.get(plan_key, {})

    if not plan:
        await update.message.reply_text(
            "⚠️ *Session Expired*\n\n"
            "Please go back to the menu and select a plan again.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END

    # Basic format validation
    if len(utr) < 6 or len(utr) > 64:
        await update.message.reply_text(
            "⚠️ *Invalid Entry*\n\n"
            "A UTR / Transaction ID is usually 6–20 characters.\n"
            "Please double-check and try again.",
            parse_mode="Markdown",
        )
        return PAY_UTR_AUTO

    # Duplicate UTR check
    if await db.is_utr_used(utr):
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await update.message.reply_text(
            f"🚫 *Already Used*\n"
            f"{DIVIDER}\n"
            f"🔖 UTR: `{utr}`\n"
            f"{DIVIDER}\n\n"
            "This UTR / Transaction ID has already been used to activate a premium plan.\n"
            "Each transaction can only be used *once*.\n\n"
            "If you believe this is an error, contact support.\n"
            f"💬 @{support}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END

    hold_msg = await update.message.reply_text(
        f"🔍 *Verifying Payment…*\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
        f"🔖 UTR: `{utr}`\n"
        f"{DIVIDER}\n\n"
        "⏳ Searching payment inbox… _This takes a few seconds._",
        parse_mode="Markdown",
    )

    await _do_autopay_verify(
        utr=utr, plan_key=plan_key, plan=plan, user_id=user_id,
        order_id=order_id, hold_msg=hold_msg, ctx=ctx,
        user=update.effective_user, is_retry=False,
    )
    return ConversationHandler.END


# ── Retry Auto-Verify ─────────────────────────────────────────────────────────
async def cb_autopay_retry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Retrying…", show_alert=False)
    user_id = update.effective_user.id

    raw = q.data.replace("autopay_retry_", "")
    try:
        plan_key, utr = raw.split("|", 1)
    except ValueError:
        await q.message.reply_text("⚠️ Could not retry. Please try again from the menu.", reply_markup=main_menu_kb())
        return

    plan = _PLANS_CACHE.get(plan_key)
    if not plan:
        await q.message.reply_text("⚠️ Plan not found. Please restart from the menu.", reply_markup=main_menu_kb())
        return

    # Duplicate check again (another user may have used same UTR in the meantime)
    if await db.is_utr_used(utr):
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await q.message.edit_text(
            f"🚫 *Already Used*\n"
            f"{DIVIDER}\n"
            f"🔖 UTR: `{utr}`\n"
            f"{DIVIDER}\n\n"
            "This UTR has already been activated for a premium plan.\n"
            f"💬 Support: @{support}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
            ]),
        )
        return

    await q.message.edit_text(
        f"🔍 *Re-checking Payment…*\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan['label']}* — ₹{plan['price']}\n"
        f"🔖 UTR: `{utr}`\n"
        f"{DIVIDER}\n\n"
        "⏳ Scanning inbox again… _Please wait._",
        parse_mode="Markdown",
    )

    await _do_autopay_verify(
        utr=utr, plan_key=plan_key, plan=plan, user_id=user_id,
        order_id="", hold_msg=q.message, ctx=ctx,
        user=update.effective_user, is_retry=True,
    )


async def cancel_autopay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "❌ Verification cancelled.",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


# ── Campaign ──────────────────────────────────────────────────────────────────
async def cb_campaign(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id

    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return

    # Ensure the Telethon session is loaded into memory.
    # _clients is an in-memory dict that is cleared on every bot restart,
    # so we must reload from the saved session file before using it.
    if not userbot.get_client(user_id):
        loaded = await userbot.load_existing_session(user_id)
        if not loaded:
            await q.message.reply_text(
                f"❌ *Session Expired*\n\n"
                f"{DIVIDER}\n"
                "Your linked Telegram account session has expired or is no longer valid.\n\n"
                "Please remove your account and add it again to continue.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [_gbtn("➕ Re-add Account", callback_data="cb_addaccount")],
                    [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
                ]),
            )
            return

    msgs = await db.get_user_messages(user_id)
    if not msgs:
        await q.message.reply_text(
            f"✉️ *No Message Set*\n\n"
            f"{DIVIDER}\n"
            "You haven't set a campaign message yet.\n\n"
            "Tap *Set Message* first, then start your campaign.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("✉️ Set Message Now", callback_data="cb_setmsg")],
                [_bbtn("🔙 Back", callback_data="cb_back")],
            ]),
        )
        return

    is_premium = await db.check_premium_active(user_id)
    stats = await db.get_stats(user_id) or {}
    already_sent = stats.get("total_sent", 0)

    _free_cap = await db.get_free_limit()
    if not is_premium and already_sent >= _free_cap:
        await q.message.reply_text(
            f"🚫 *Free Limit Reached*\n\n"
            f"{DIVIDER}\n"
            f"You've used all *{_free_cap}* free sends.\n\n"
            "Upgrade to *VIP Premium* for unlimited sending! 👑",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("👑 Go VIP Premium", callback_data="cb_premium")],
                [_bbtn("🔙 Back", callback_data="cb_back")],
            ]),
        )
        return

    init_text = (
        f"🚀 *Campaign Launched!*\n\n"
        f"{DIVIDER}\n"
        f"📊 Total DMs: `scanning…`\n"
        f"📨 Sent: `0`  |  ❌ Failed: `0`\n"
        f"⚡ Speed: `0.0` msg/sec\n"
        f"📍 Last: —\n"
        f"{DIVIDER}"
    )
    prog_msg = await q.message.reply_text(init_text, parse_mode="Markdown", reply_markup=_stop_kb())
    _progress_msg_ids[user_id] = prog_msg.message_id
    _progress_last_edit[user_id] = time.monotonic()
    _campaign_start_times[user_id] = time.monotonic()

    async def on_progress(uid, sent, failed, total, label):
        try:
            now = time.monotonic()
            if sent not in (0, total) and now - _progress_last_edit.get(uid, 0) < 1.0:
                return
            _progress_last_edit[uid] = now
            msg_id = _progress_msg_ids.get(uid)
            if not msg_id:
                return
            last = label or "—"
            elapsed = now - _campaign_start_times.get(uid, now)
            speed = sent / max(elapsed, 1)
            total_label = f"{total:,}" if total else "scanning…"
            text = (
                f"🚀 *Campaign Running…*\n\n"
                f"{DIVIDER}\n"
                f"📊 Total DMs: `{total_label}`\n"
                f"📨 Sent: `{sent:,}`  |  ❌ Failed: `{failed:,}`\n"
                f"⚡ Speed: `{speed:.1f}` msg/sec\n"
                f"📍 Last: {last}\n"
                f"{DIVIDER}"
            )
            await ctx.bot.edit_message_text(
                chat_id=uid, message_id=msg_id,
                text=text, parse_mode="Markdown", reply_markup=_stop_kb(),
            )
        except Exception:
            pass

    async def on_done(uid, error):
        try:
            msg_id = _progress_msg_ids.pop(uid, None)
            _progress_last_edit.pop(uid, None)
            _campaign_start_times.pop(uid, None)

            if error == "free_limit":
                camp = await db.get_campaign(uid)
                _cap = await db.get_free_limit()
                sent = camp["sent"] if camp else _cap
                done_text = (
                    f"🛑 *Free Limit Reached — Campaign Stopped!*\n\n"
                    f"{DIVIDER}\n"
                    f"📨 DMs Sent: *{sent:,}* / {_cap}\n"
                    f"🔒 Free plan limit: *{_cap} sends*\n"
                    f"{DIVIDER}\n\n"
                    f"🚀 *Want to keep going?*\n"
                    f"Upgrade to *VIP Premium* and send to unlimited contacts — no cap, ever!\n\n"
                    f"👑 Plans start at just ₹10/day."
                )
                kb = InlineKeyboardMarkup([
                    [_gbtn("👑 Go VIP Premium — Unlimited Sends", callback_data="cb_premium")],
                    [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
                ])
                if msg_id:
                    await ctx.bot.edit_message_text(chat_id=uid, message_id=msg_id, text=done_text, parse_mode="Markdown", reply_markup=kb)
                else:
                    await ctx.bot.send_message(chat_id=uid, text=done_text, parse_mode="Markdown", reply_markup=kb)

            elif error == "stopped":
                camp = await db.get_campaign(uid)
                sent = camp["sent"] if camp else 0
                done_text = (
                    f"⛔ *Campaign Stopped*\n\n"
                    f"{DIVIDER}\n"
                    f"Messages sent before stopping: `{sent:,}`"
                )
                if msg_id:
                    await ctx.bot.edit_message_text(chat_id=uid, message_id=msg_id, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())
                else:
                    await ctx.bot.send_message(chat_id=uid, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())

            elif error:
                done_text = f"❌ *Campaign Error*\n\n`{error}`"
                if msg_id:
                    await ctx.bot.edit_message_text(chat_id=uid, message_id=msg_id, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())
                else:
                    await ctx.bot.send_message(chat_id=uid, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())

            else:
                camp = await db.get_campaign(uid)
                total = camp["total"] if camp else 0
                sent = camp["sent"] if camp else 0
                bar = _build_progress_bar(sent, total)
                done_text = (
                    f"✅ *Campaign Complete!*\n\n"
                    f"{DIVIDER}\n"
                    f"`[{bar}]` 100%\n"
                    f"📨 Sent to *{sent:,}* DMs\n"
                    f"🎯 Out of *{total:,}* total contacts\n"
                    f"{DIVIDER}\n\n"
                    "Great job! 🚀 Start another campaign anytime."
                )
                if msg_id:
                    await ctx.bot.edit_message_text(chat_id=uid, message_id=msg_id, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())
                else:
                    await ctx.bot.send_message(chat_id=uid, text=done_text, parse_mode="Markdown", reply_markup=main_menu_kb())

            # ── Referral step 2: first DM sent → complete referral ─────────────
            try:
                camp = await db.get_campaign(uid)
                if camp and camp.get("sent", 0) > 0:
                    result = await db.try_complete_referral(uid)
                    if result:
                        referrer_id = result["referrer_id"]
                        # Per-referral reward
                        await db.extend_premium(referrer_id, result["reward_days"], "referral")

                        # Check if this referral hit a milestone → grant bonus days
                        referrer_stats = await db.get_referrer_stats(referrer_id)
                        new_total = referrer_stats["completed"]
                        milestone_bonus = db.get_milestone_bonus(new_total)
                        milestone_text = ""
                        if milestone_bonus:
                            await db.extend_premium(referrer_id, milestone_bonus, "milestone")
                            next_ms = db.get_next_milestone(new_total)
                            next_hint = (
                                f"🎯 Next milestone: *{next_ms[0]} refs → {next_ms[1]} days*"
                                if next_ms else "🏆 All milestones unlocked!"
                            )
                            milestone_text = (
                                f"\n🏅 *MILESTONE UNLOCKED!* {new_total} referrals!\n"
                                f"🎁 *+{milestone_bonus} bonus day(s)* added!\n"
                                f"{next_hint}\n"
                            )

                        await ctx.bot.send_message(
                            chat_id=referrer_id,
                            text=(
                                f"🎉 *Referral Completed!*\n\n"
                                f"{DIVIDER}\n"
                                f"👤 *{result['referred_name']}* just completed your referral!\n"
                                f"   ✅ Added account\n"
                                f"   ✅ Sent their first DM campaign\n\n"
                                f"🎁 *+{result['reward_days']} day(s) VIP Premium* added!\n"
                                f"👥 Total Referrals: *{new_total}*\n"
                                f"{milestone_text}"
                                f"{DIVIDER}\n\n"
                                f"Keep sharing to reach the next milestone! 🚀"
                            ),
                            parse_mode="Markdown",
                        )
            except Exception:
                pass
            # ─────────────────────────────────────────────────────────────────

        except Exception:
            pass

    await userbot.start_campaign(user_id, msgs, on_progress, on_done)


# ── Stop Campaign ─────────────────────────────────────────────────────────────
async def _clear_campaign_state(user_id: int):
    """Fully wipe every in-memory trace of a campaign for this user."""
    await userbot.cancel_campaign(user_id)
    _progress_msg_ids.pop(user_id, None)
    _progress_last_edit.pop(user_id, None)
    _campaign_start_times.pop(user_id, None)
    try:
        await db.update_campaign(user_id, status="cancelled")
    except Exception:
        pass


async def cb_stop_campaign(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Stopping…", show_alert=False)
    user_id = update.effective_user.id
    msg_id = _progress_msg_ids.get(user_id)  # read before clearing
    await _clear_campaign_state(user_id)
    camp = await db.get_campaign(user_id)
    sent = camp["sent"] if camp else 0
    text = (
        f"⛔ *Campaign Stopped*\n\n"
        f"{DIVIDER}\n"
        f"📨 Messages sent before stopping: `{sent:,}`\n\n"
        "You can start a new campaign any time."
    )
    try:
        if msg_id:
            await q.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
        else:
            await q.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())


# ── Set Message conversation ──────────────────────────────────────────────────
async def cb_setmsg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)

    if not await ensure_account(update):
        return

    ctx.user_data["msg_count"] = 0
    user_id = update.effective_user.id
    await db.clear_messages(user_id)

    await q.message.reply_text(
        f"✉️ *COMPOSE CAMPAIGN MESSAGE*\n"
        f"{DIVIDER}\n\n"
        "Send your *text*, *link*, or *image* now.\n\n"
        "💡 *Tips:*\n"
        "• You can add multiple messages — each gets sent separately\n"
        "• Mix text and images freely\n"
        "• Keep it concise for better response rates\n\n"
        f"{DIVIDER}\n"
        "Send your first message 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return SET_MSG_COLLECT


async def handle_set_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = ctx.user_data.get("msg_count", 0) + 1
    ctx.user_data["msg_count"] = count

    msg = update.message

    # ── Detect "no link preview" ───────────────────────────────────────────
    # When the user sends a message with link preview disabled (tap the
    # preview toggle before sending in Telegram), we honour that and send
    # to all DMs the same way — no preview card.
    no_preview = bool(
        getattr(msg, "link_preview_options", None)
        and getattr(msg.link_preview_options, "is_disabled", False)
    )

    # ── Detect replied-to message ──────────────────────────────────────────
    # If the user replies to a message while composing, we capture the
    # quoted text and prepend it so the DM looks exactly as they composed it.
    quoted_prefix = ""
    if msg.reply_to_message:
        quoted = msg.reply_to_message
        quoted_text = (
            quoted.text
            or quoted.caption
            or ("[media]" if quoted.photo or quoted.video or quoted.document else "")
        )
        if quoted_text:
            quoted_prefix = f"❝ {quoted_text} ❞\n\n"

    if msg.photo:
        photo = msg.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        path = os.path.join("data", f"media_{user_id}_{count}.jpg")
        await file.download_to_drive(path)
        caption = quoted_prefix + (msg.caption or "")
        await db.add_message(user_id, content=caption, media_path=path, media_type="photo",
                             link_preview_disabled=no_preview)
        type_label = "📸 Image"

    elif msg.document:
        file = await ctx.bot.get_file(msg.document.file_id)
        path = os.path.join("data", f"media_{user_id}_{count}_{msg.document.file_name}")
        await file.download_to_drive(path)
        caption = quoted_prefix + (msg.caption or "")
        await db.add_message(user_id, content=caption, media_path=path, media_type="document",
                             link_preview_disabled=no_preview)
        type_label = "📎 File"

    else:
        text = quoted_prefix + (msg.text or "")
        await db.add_message(user_id, content=text, link_preview_disabled=no_preview)
        type_label = "💬 Text"

    preview_note = "  _(no link preview)_" if no_preview else ""
    reply_note = "  _(with quoted reply)_" if quoted_prefix else ""

    await update.message.reply_text(
        f"✅ *{type_label} saved! ({count} total)*{preview_note}{reply_note}\n\n"
        "Send another message to add more,\n"
        "or tap *Done* to finish.",
        parse_mode="Markdown",
        reply_markup=done_kb(count),
    )
    return SET_MSG_COLLECT


async def handle_msg_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    count = ctx.user_data.get("msg_count", 0)
    await q.message.reply_text(
        f"🎯 *{count} message(s) ready!*\n\n"
        f"{DIVIDER}\n"
        "Tap *Start DM Campaign* to begin sending instantly.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_gbtn("🚀 Start DM Campaign", callback_data="cb_campaign")],
            [_bbtn("📋 Preview Message", callback_data="cb_previewmsg")],
            [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
        ]),
    )
    ctx.user_data["msg_count"] = 0
    return ConversationHandler.END


async def cancel_setmsg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Campaign — Channel Join Requesters flow ───────────────────────────────────
async def cb_campaign_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)

    if not await ensure_account(update):
        return ConversationHandler.END
    if not await ensure_not_banned(update):
        return ConversationHandler.END

    msgs = await db.get_user_messages(update.effective_user.id)
    if not msgs:
        await q.message.reply_text(
            f"✉️ *No Message Set*\n\n"
            f"{DIVIDER}\n"
            "Set a campaign message first, then choose your target.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("✉️ Set Message Now", callback_data="cb_setmsg")],
                [_bbtn("🔙 Back", callback_data="cb_back")],
            ]),
        )
        return ConversationHandler.END

    await q.message.reply_text(
        f"📣 *CAMPAIGN — CHANNEL JOIN REQUESTERS*\n\n"
        f"{DIVIDER}\n"
        "Your message will be sent to users with pending join requests.\n\n"
        "Send your channel link or username:\n\n"
        "🔓 Public: `@MyChannel` or `https://t.me/MyChannel`\n"
        "🔒 Private: `https://t.me/+InviteHash`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return CAMP_CHANNEL_INPUT


async def handle_camp_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    channel, label = _parse_channel_input(text)
    ctx.user_data["camp_channel"] = channel
    ctx.user_data["camp_label"] = label

    wait_msg = await update.message.reply_text(
        f"⏳ Fetching pending join requests for `{label}`…",
        parse_mode="Markdown",
    )

    try:
        importers, total = await userbot.get_pending_join_requests(user_id, channel)
    except Exception as ex:
        await wait_msg.edit_text(
            f"❌ *Error fetching requests*\n\n`{ex}`\n\n"
            "Make sure you are an admin of that channel.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if total == 0:
        await wait_msg.edit_text(
            f"ℹ️ *No pending join requests* found for `{label}`.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    is_premium = await db.check_premium_active(user_id)
    free_limit = await db.get_free_limit()
    cap = 999_999 if is_premium else free_limit
    available = min(total, cap)
    ctx.user_data["camp_importers"] = [imp.user_id for imp in importers[:available]]
    ctx.user_data["camp_total"] = total

    limit_note = "Unlimited (VIP)" if is_premium else f"Free limit: {free_limit}"
    await wait_msg.edit_text(
        f"👥 *Pending Join Requests: {total}*\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"💎 {limit_note}\n\n"
        f"Send a number (1–{available}) for how many users to DM:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return CAMP_COUNT_INPUT


async def handle_camp_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Send a valid integer (e.g. 50).")
        return CAMP_COUNT_INPUT

    is_premium = await db.check_premium_active(user_id)
    free_limit = await db.get_free_limit()
    importers = ctx.user_data.get("camp_importers", [])
    label = ctx.user_data.get("camp_label", "channel")

    if not is_premium and amount > free_limit:
        await update.message.reply_text(
            f"❌ *Free limit is {free_limit}.*\n\n"
            "Upgrade to VIP Premium for more DMs! 👑",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("👑 Go VIP Premium", callback_data="cb_premium")],
                [_rbtn("🔙 Cancel", callback_data="cb_back")],
            ]),
        )
        return CAMP_COUNT_INPUT

    targets = importers[:amount]
    msgs = await db.get_user_messages(user_id)
    client = userbot.get_client(user_id)
    if not client or not await client.is_user_authorized():
        await update.message.reply_text(
            "❌ Your account is not linked. Please add your account first.",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    prog_msg = await update.message.reply_text(
        f"🚀 *Campaign Launched!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Targets: *{len(targets)}*\n"
        f"`[{'░' * 18}]` 0%\n"
        f"📨 Sent: `0` / `{len(targets)}`\n"
        f"❌ Failed: `0`",
        parse_mode="Markdown",
        reply_markup=_stop_kb(),
    )

    sent = 0
    failed = 0
    batch_size = 500

    for i, uid in enumerate(targets, 1):
        try:
            entity = await client.get_entity(uid)
            for msg in msgs:
                if msg.get("media_path") and os.path.exists(msg["media_path"]):
                    await client.send_file(entity, msg["media_path"], caption=msg.get("content") or "")
                elif msg.get("content"):
                    await client.send_message(entity, msg["content"])
            sent += 1
        except Exception:
            failed += 1

        # Live progress update every batch_size sends or at end
        if i % batch_size == 0 or i == len(targets):
            pct = round(100 * sent / len(targets))
            filled = round(18 * sent / len(targets))
            bar = "█" * filled + "░" * (18 - filled)
            try:
                await prog_msg.edit_text(
                    f"🚀 *Campaign Running…*\n\n"
                    f"{DIVIDER}\n"
                    f"📣 Channel: `{label}`\n"
                    f"`[{bar}]` {pct}%\n"
                    f"📨 Sent: `{sent:,}` / `{len(targets):,}`\n"
                    f"❌ Failed: `{failed:,}`",
                    parse_mode="Markdown",
                    reply_markup=_stop_kb(),
                )
            except Exception:
                pass
        await asyncio.sleep(0.5)

    bar_full = "█" * 18
    await prog_msg.edit_text(
        f"✅ *Campaign Complete!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"`[{bar_full}]` 100%\n"
        f"📨 Sent: *{sent:,}* / {len(targets):,}\n"
        f"❌ Failed: *{failed:,}*\n"
        f"{DIVIDER}\n\n"
        "Great job! 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel_camp_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Admin /setlimit command ───────────────────────────────────────────────────
async def cmd_setlimit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_TG_ID:
        return
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/setlimit <number>`\n\nExample: `/setlimit 200`",
            parse_mode="Markdown",
        )
        return
    new_limit = max(1, int(args[0]))
    await db.set_free_limit(new_limit)
    await update.message.reply_text(
        f"✅ *Free DM limit updated to: {new_limit}*",
        parse_mode="Markdown",
    )


# ── Add Account conversation ──────────────────────────────────────────────────
async def cb_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)
    user_id = update.effective_user.id
    acc = await db.get_account(user_id)
    if acc:
        await q.message.reply_text(
            f"✅ *Account Already Linked*\n\n"
            f"{DIVIDER}\n"
            f"📱 Phone: `{acc['phone']}`\n\n"
            "Use *Remove Account* first if you want to switch accounts.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    await q.message.reply_text(
        f"➕ *ADD YOUR TELEGRAM ACCOUNT*\n"
        f"{DIVIDER}\n\n"
        "*Step 1 of 3 — Phone Number*\n\n"
        "Enter your phone number with country code:\n"
        "Example: `+91XXXXXXXXXX`\n\n"
        "🔒 _Your account is only used to send DMs — we never access personal data._",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_PHONE


async def handle_add_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    user_id = update.effective_user.id

    if not phone.startswith("+"):
        await update.message.reply_text(
            "⚠️ Include country code. Example: `+91XXXXXXXXXX`",
            parse_mode="Markdown",
        )
        return ADD_PHONE

    await update.message.reply_text(
        f"📲 *Sending OTP to {phone}…*\n\n"
        "_Please wait a moment…_",
        parse_mode="Markdown",
    )
    try:
        phone_code_hash = await userbot.send_code(user_id, phone)
    except Exception as ex:
        await update.message.reply_text(
            f"❌ *Failed to Send OTP*\n\n"
            f"{DIVIDER}\n"
            f"Error: `{ex}`\n\n"
            "Please double-check your number and try again.\n"
            "Make sure your API credentials are correct.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END

    ctx.user_data["phone"] = phone
    ctx.user_data["phone_code_hash"] = phone_code_hash
    await db.upsert_user(user_id, phone=phone, phone_code_hash=phone_code_hash, state="code")

    await update.message.reply_text(
        f"✅ *OTP Sent to {phone}!*\n\n"
        f"{DIVIDER}\n"
        "*Step 2 of 3 — Enter OTP*\n\n"
        "Check your Telegram app for the code.\n"
        "Enter it with a space between every digit:\n"
        "Example: `1 2 3 4 5`",
        parse_mode="Markdown",
    )
    return ADD_CODE


async def handle_add_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().replace(" ", "")
    user_id = update.effective_user.id
    phone = ctx.user_data.get("phone")
    phone_code_hash = ctx.user_data.get("phone_code_hash")

    try:
        await userbot.sign_in(user_id, phone, code, phone_code_hash)
        await db.add_account(user_id, phone)
        await db.upsert_user(user_id, state="idle")
        await db.mark_referral_account_added(user_id)   # referral step 1
        stats = await db.get_stats(user_id) or {}
        await update.message.reply_text(
            f"🎉 *Congratulations! Your Telegram account has been added successfully.*\n\n"
            f"{DIVIDER}\n"
            f"📱 Phone: `{phone}`\n"
            f"🆓 Free sends available: *{await db.get_free_limit()}*\n"
            f"{DIVIDER}\n\n"
            "You can now start using all of the available services and features. 🚀",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END
    except Exception as ex:
        if "password" in str(ex).lower() or "2fa" in str(ex).lower() or "SessionPasswordNeeded" in str(ex):
            ctx.user_data["code"] = code
            await update.message.reply_text(
                f"🔐 *2FA Password Required*\n\n"
                f"{DIVIDER}\n"
                "*Step 3 of 3 — Two-Factor Authentication*\n\n"
                "Your account has 2FA enabled.\n"
                "Enter your Telegram 2FA password:",
                parse_mode="Markdown",
            )
            return ADD_2FA
        await update.message.reply_text(
            f"❌ *Invalid OTP*\n\n"
            f"{DIVIDER}\n"
            f"Error: `{ex}`\n\n"
            "Please try again with the correct code.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END


async def handle_add_2fa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = update.effective_user.id
    phone = ctx.user_data.get("phone")

    try:
        await userbot.sign_in_2fa(user_id, password)
        await db.add_account(user_id, phone)
        await db.upsert_user(user_id, state="idle")
        await db.mark_referral_account_added(user_id)   # referral step 1
        await update.message.reply_text(
            f"🎉 *Congratulations! Your Telegram account has been added successfully.*\n\n"
            f"{DIVIDER}\n"
            f"📱 Phone: `{phone}`\n"
            f"🔐 2FA: ✅ Verified\n"
            f"🆓 Free sends: *{FREE_DM_LIMIT}*\n"
            f"{DIVIDER}\n\n"
            "You can now start using all of the available services and features. 🚀",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
    except Exception as ex:
        await update.message.reply_text(
            f"❌ *Wrong 2FA Password*\n\n"
            f"Error: `{ex}`\n\n"
            "Please try again.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
    return ConversationHandler.END


# ── Gift Code ─────────────────────────────────────────────────────────────────
async def cb_giftcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)
    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return
    await q.message.reply_text(
        f"🎁 *REDEEM GIFT CODE*\n"
        f"{DIVIDER}\n\n"
        "Enter your gift code below:\n"
        "Example: `A1B2C3D4`\n\n"
        "_Gift codes grant free premium days instantly._",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return GIFT_CODE_INPUT


async def handle_gift_code_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = update.message.text.strip().upper()

    row = await db.use_gift_code(code, user_id)
    if not row:
        await update.message.reply_text(
            f"❌ *Invalid or Fully Used Code*\n\n"
            f"{DIVIDER}\n"
            f"Code: `{code}`\n\n"
            "This code is either invalid or has reached its maximum number of uses.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("🔄 Try Again", callback_data="cb_giftcode")],
                [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
            ]),
        )
        return ConversationHandler.END

    days = row["days"]
    label = "Unlimited (Lifetime)" if days >= 999 else f"{days} day(s)"
    await db.set_premium(user_id, f"gift_{days}d", days)
    await db.increment_plans(user_id)

    await update.message.reply_text(
        f"🎉 *Gift Code Redeemed!*\n\n"
        f"{DIVIDER}\n"
        f"✅ Code: `{code}`\n"
        f"👑 Premium: *{label}*\n"
        f"{DIVIDER}\n\n"
        "Your premium is now active. Enjoy unlimited DMs! 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_giftcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Accept Pending Join Requests ──────────────────────────────────────────────
async def cb_acceptpending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)

    if not await ensure_account(update):
        return
    if not await ensure_not_banned(update):
        return

    user_id = update.effective_user.id
    is_premium = await db.check_premium_active(user_id)
    limit_text = "Unlimited" if is_premium else f"{FREE_ACCEPT_LIMIT}"

    await q.message.reply_text(
        f"✅ *ACCEPT PENDING JOIN REQUESTS*\n\n"
        f"{DIVIDER}\n"
        f"💎 Your limit: *{limit_text} requests per use*\n"
        f"{DIVIDER}\n\n"
        "Send the channel username or link — public *and* private both work:\n\n"
        "🔓 Public:  `@MyChannel`  ·  `t.me/MyChannel`\n"
        "🔒 Private: `t.me/+InviteHash`  ·  `telegram.me/+InviteHash`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return AP_CHANNEL_INPUT


def _parse_channel_input(text: str):
    """
    Normalise any channel input the user might type.

    Accepted formats:
      Public   : @username | t.me/username | telegram.me/username
      Private  : t.me/+Hash | telegram.me/+Hash | t.me/joinchat/Hash
                 telegram.me/joinchat/Hash

    Returns (channel_ref, display_label):
      - Public:  channel_ref = "@username",  display_label = "@username"
      - Private: channel_ref = canonical https://t.me/… URL, display_label = short hash
    """
    text = text.strip()

    # ── Normalise telegram.me → t.me for unified parsing ──────────────────
    text = text.replace("https://telegram.me/", "https://t.me/")
    text = text.replace("http://telegram.me/",  "https://t.me/")
    text = text.replace("telegram.me/",         "t.me/")

    # ── Private invite link: t.me/+ or t.me/joinchat/ ─────────────────────
    if "t.me/+" in text or "t.me/joinchat/" in text:
        if "t.me/+" in text:
            invite_hash = text.split("t.me/+")[-1].rstrip("/").split("?")[0]
            raw = f"https://t.me/+{invite_hash}"
        else:
            invite_hash = text.split("t.me/joinchat/")[-1].rstrip("/").split("?")[0]
            raw = f"https://t.me/joinchat/{invite_hash}"
        return raw, f"+{invite_hash[:14]}…"

    # ── Public: strip to bare username then add @ ──────────────────────────
    if "t.me/" in text:
        username = text.split("t.me/")[-1].rstrip("/").split("?")[0]
    elif text.startswith("@"):
        username = text[1:]
    else:
        username = text.lstrip("@")

    return f"@{username}", f"@{username}"


async def handle_ap_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    channel, label = _parse_channel_input(text)
    ctx.user_data["ap_channel"] = channel
    ctx.user_data["ap_label"] = label

    wait_msg = await update.message.reply_text(
        f"⏳ Fetching pending requests for `{label}`…",
        parse_mode="Markdown",
    )

    try:
        users, total = await userbot.get_pending_join_requests(user_id, channel)
    except Exception as ex:
        await wait_msg.edit_text(
            f"❌ *Could Not Fetch Requests*\n\n"
            f"{DIVIDER}\n"
            f"Error: `{ex}`\n\n"
            "Make sure:\n"
            "• The channel link / username is correct\n"
            "• Your linked account is an admin of that channel\n"
            "• Join requests are enabled in the channel settings\n"
            "• For private channels, paste the full invite link (e.g. `https://t.me/+abc123`)",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if total == 0:
        await wait_msg.edit_text(
            f"ℹ️ *No Pending Requests*\n\n"
            f"{DIVIDER}\n"
            f"Channel: `{label}`\n"
            f"Pending: *0*\n\n"
            "There are no pending join requests to accept right now.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    is_premium = await db.check_premium_active(user_id)
    max_allowed = 999_999 if is_premium else FREE_ACCEPT_LIMIT
    ctx.user_data["ap_total"] = total
    ctx.user_data["ap_max"] = max_allowed

    cap = min(total, max_allowed)
    plan_note = (
        ""
        if is_premium
        else f"\n\n⚠️ Free plan: max *{FREE_ACCEPT_LIMIT}* per use. Upgrade for unlimited 👑"
    )

    await wait_msg.edit_text(
        f"📋 *Pending Requests Found!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Total Pending: *{total:,}*\n"
        f"💎 Your Limit: *{'Unlimited' if is_premium else FREE_ACCEPT_LIMIT}*\n"
        f"{DIVIDER}\n\n"
        f"How many requests do you want to accept?\n"
        f"Send a number between 1 and {cap:,}:{plan_note}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return AP_COUNT_INPUT


async def handle_ap_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    channel = ctx.user_data.get("ap_channel", "")
    label = ctx.user_data.get("ap_label", channel)
    total = ctx.user_data.get("ap_total", 0)
    max_allowed = ctx.user_data.get("ap_max", FREE_ACCEPT_LIMIT)

    try:
        count = int(text)
        if count <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please send a valid number, e.g. `50`.",
            parse_mode="Markdown",
        )
        return AP_COUNT_INPUT

    is_premium = await db.check_premium_active(user_id)

    if count > max_allowed and not is_premium:
        await update.message.reply_text(
            f"🚫 *Free Plan Limit*\n\n"
            f"{DIVIDER}\n"
            f"You can accept up to *{FREE_ACCEPT_LIMIT}* requests on the free plan.\n\n"
            "Upgrade to *VIP Premium* for unlimited! 👑",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("👑 Go VIP Premium", callback_data="cb_premium")],
                [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
            ]),
        )
        return ConversationHandler.END

    count = min(count, total, max_allowed)

    wait_msg = await update.message.reply_text(
        f"⏳ *Accepting {count:,} requests…*\n\n"
        "_Please wait, this may take a moment._",
        parse_mode="Markdown",
    )

    try:
        accepted, _ = await userbot.accept_join_requests(user_id, channel, count)
    except Exception as ex:
        await wait_msg.edit_text(
            f"❌ *Error*\n\n"
            f"{DIVIDER}\n"
            f"`{ex}`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    skipped = total - count
    await wait_msg.edit_text(
        f"✅ *Done — Requests Accepted!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"✅ Accepted: *{accepted:,}*\n"
        f"⏭ Skipped: *{skipped:,}*\n"
        f"👥 Total Pending Was: *{total:,}*\n"
        f"{DIVIDER}\n\n"
        "All done! 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_acceptpending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Join Request DM ───────────────────────────────────────────────────────────
async def cb_joinrequestdm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)

    if not await ensure_account(update):
        return ConversationHandler.END
    if not await ensure_not_banned(update):
        return ConversationHandler.END

    await q.message.reply_text(
        f"👥 *JOIN REQUEST DM*\n\n"
        f"{DIVIDER}\n"
        "Send DMs directly to users who have pending join requests on your channel.\n\n"
        "📢 Send your channel link or username:\n\n"
        "🔓 Public:  `@MyChannel`  ·  `t.me/MyChannel`\n"
        "🔒 Private: `t.me/+InviteHash`  ·  `telegram.me/+InviteHash`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return JD_CHANNEL_INPUT


async def handle_jd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    channel, label = _parse_channel_input(text)
    ctx.user_data["jd_channel"] = channel
    ctx.user_data["jd_label"] = label

    wait_msg = await update.message.reply_text(
        f"⏳ Fetching pending join requests for `{label}`…",
        parse_mode="Markdown",
    )

    try:
        importers, total = await userbot.get_pending_join_requests(user_id, channel)
    except Exception as ex:
        await wait_msg.edit_text(
            f"❌ *Error fetching requests*\n\n`{ex}`\n\n"
            "Make sure you are an admin of that channel.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if total == 0:
        await wait_msg.edit_text(
            f"ℹ️ *No pending join requests* found for `{label}`.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    is_premium = await db.check_premium_active(user_id)
    free_limit = await db.get_free_limit()

    # Store the REAL total from Telegram — never cap it here.
    # The per-plan limit is enforced freshly in handle_jd_count_input so
    # that a premium status change between steps always uses the current value.
    ctx.user_data["jd_total"] = total

    max_for_user = total if is_premium else min(total, free_limit)

    await wait_msg.edit_text(
        f"👥 *Pending Join Requests Found!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Total Pending: *{total:,}*\n"
        f"💎 Your Limit: *{'Unlimited' if is_premium else str(free_limit)}*\n"
        f"{DIVIDER}\n\n"
        f"How many users do you want to DM? Please enter the number.\n\n"
        f"📌 Examples: `10`, `20`, `25`, `60`\n\n"
        f"_(Max for you right now: {max_for_user:,})_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return JD_COUNT_INPUT


async def handle_jd_count_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    label    = ctx.user_data.get("jd_label", "channel")
    jd_total = ctx.user_data.get("jd_total", 0)

    # Always re-check premium status here — the user may have received premium
    # after the channel-scan step, so we must not rely on a stale stored cap.
    is_premium = await db.check_premium_active(user_id)
    free_limit = await db.get_free_limit()

    # Available = real Telegram total for premium users, capped for free users
    available = jd_total if is_premium else min(jd_total, free_limit)

    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid number greater than 0.\n\n"
            "📌 Examples: `10`, `50`, `444`",
            parse_mode="Markdown",
        )
        return JD_COUNT_INPUT

    # Free plan cap — shown clearly with upgrade option
    if not is_premium and amount > free_limit:
        await update.message.reply_text(
            f"🚫 *Free Plan Limit*\n\n"
            f"{DIVIDER}\n"
            f"Free plan allows up to *{free_limit}* users per campaign.\n"
            f"You entered *{amount:,}* — upgrade to send to any number!\n\n"
            "👑 *VIP Premium* = unlimited targets, no restrictions.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [_gbtn("👑 Upgrade to VIP Premium", callback_data="cb_premium")],
                [_rbtn("🔙 Cancel",                 callback_data="cb_back")],
            ]),
        )
        return JD_COUNT_INPUT

    # Can't target more than what actually exists in the channel
    if amount > jd_total:
        await update.message.reply_text(
            f"⚠️ Only *{jd_total:,}* pending join requests exist for `{label}`.\n"
            f"Please enter a number between *1* and *{jd_total:,}*.",
            parse_mode="Markdown",
        )
        return JD_COUNT_INPUT

    ctx.user_data["jd_amount"] = amount

    await update.message.reply_text(
        f"✅ *Target set — {amount:,} users*\n\n"
        f"{DIVIDER}\n"
        "Now send the *message* you want to DM to these users.\n\n"
        "💡 Supported: text, link, photo, video, document, audio, voice, sticker.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return JD_MSG_INPUT


async def handle_jd_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    msg      = update.message
    amount   = ctx.user_data.get("jd_amount", 0)
    label    = ctx.user_data.get("jd_label", "channel")
    channel  = ctx.user_data.get("jd_channel", "")

    # ── Detect and download any media ────────────────────────────────────────
    media_path   = None
    media_type   = None   # "photo" | "video" | "document" | "audio" | "voice" | "sticker"
    text_content = ""

    if msg.photo:
        tg_file    = await ctx.bot.get_file(msg.photo[-1].file_id)
        media_path = os.path.join("data", f"jd_media_{user_id}.jpg")
        await tg_file.download_to_drive(media_path)
        media_type   = "photo"
        text_content = msg.caption or ""

    elif msg.video:
        tg_file    = await ctx.bot.get_file(msg.video.file_id)
        media_path = os.path.join("data", f"jd_media_{user_id}.mp4")
        await tg_file.download_to_drive(media_path)
        media_type   = "video"
        text_content = msg.caption or ""

    elif msg.document:
        tg_file    = await ctx.bot.get_file(msg.document.file_id)
        ext        = os.path.splitext(msg.document.file_name or "file")[1] or ".bin"
        media_path = os.path.join("data", f"jd_media_{user_id}{ext}")
        await tg_file.download_to_drive(media_path)
        media_type   = "document"
        text_content = msg.caption or ""

    elif msg.audio:
        tg_file    = await ctx.bot.get_file(msg.audio.file_id)
        media_path = os.path.join("data", f"jd_media_{user_id}.mp3")
        await tg_file.download_to_drive(media_path)
        media_type   = "audio"
        text_content = msg.caption or ""

    elif msg.voice:
        tg_file    = await ctx.bot.get_file(msg.voice.file_id)
        media_path = os.path.join("data", f"jd_media_{user_id}.ogg")
        await tg_file.download_to_drive(media_path)
        media_type   = "voice"
        text_content = msg.caption or ""

    elif msg.sticker:
        tg_file    = await ctx.bot.get_file(msg.sticker.file_id)
        media_path = os.path.join("data", f"jd_media_{user_id}.webp")
        await tg_file.download_to_drive(media_path)
        media_type   = "sticker"
        text_content = ""

    else:
        text_content = msg.text or ""

    if not text_content and not media_path:
        await msg.reply_text(
            "⚠️ Please send a message (text, link, photo, video, document, audio, voice, or sticker).",
            parse_mode="Markdown",
        )
        return JD_MSG_INPUT

    # ── Fetch users ───────────────────────────────────────────────────────────
    prog_msg = await msg.reply_text(
        f"⏳ *Fetching {amount:,} users from join requests…*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Target: *{amount:,}*\n\n"
        "Please wait…",
        parse_mode="Markdown",
    )

    try:
        target_users, _ = await userbot.fetch_join_request_users(user_id, channel, amount)
    except Exception as ex:
        await prog_msg.edit_text(
            f"❌ *Failed to fetch join request users*\n\n`{ex}`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if not target_users:
        await prog_msg.edit_text(
            "❌ No pending join request users found. They may have already been processed.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    actual_target = len(target_users)

    client = userbot.get_client(user_id)
    if not client or not await client.is_user_authorized():
        await prog_msg.edit_text(
            "❌ Your Telegram account is not linked. Please add your account first.",
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    await prog_msg.edit_text(
        f"🚀 *Sending Join Request DMs…*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Total Target: *{actual_target:,}*\n"
        f"📨 Sent: `0` / `{actual_target:,}`\n"
        f"🔄 Remaining: `{actual_target:,}`\n"
        f"`[{'░' * 18}]` 0%",
        parse_mode="Markdown",
    )

    # ── Send loop ─────────────────────────────────────────────────────────────
    sent   = 0
    failed = 0

    for user in target_users:
        try:
            if media_path and os.path.exists(media_path):
                # send_file handles photos, videos, documents, audio, voice, stickers
                await client.send_file(
                    user,
                    media_path,
                    caption=text_content or None,
                )
            elif text_content:
                await client.send_message(user, text_content)
            sent += 1
        except Exception:
            failed += 1

        done = sent + failed
        if done % 5 == 0 or done == actual_target:
            pct      = round(100 * done / actual_target)
            filled   = round(18 * done / actual_target)
            bar      = "█" * filled + "░" * (18 - filled)
            remaining = actual_target - done
            try:
                await prog_msg.edit_text(
                    f"🚀 *Sending Join Request DMs…*\n\n"
                    f"{DIVIDER}\n"
                    f"📣 Channel: `{label}`\n"
                    f"👥 Total Target: *{actual_target:,}*\n"
                    f"📨 Sent: `{sent:,}` / `{actual_target:,}`\n"
                    f"🔄 Remaining: `{remaining:,}`\n"
                    f"`[{bar}]` {pct}%",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        await asyncio.sleep(0.3)

    await prog_msg.edit_text(
        f"✅ *Join Request DM Complete!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel: `{label}`\n"
        f"👥 Total Target: *{actual_target:,}*\n"
        f"📨 Sent: *{sent:,}*\n"
        f"❌ Failed: *{failed:,}*\n"
        f"{DIVIDER}\n\n"
        "Great job! 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    # Clean up downloaded media
    if media_path and os.path.exists(media_path):
        try:
            os.remove(media_path)
        except Exception:
            pass

    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel_joinrequestdm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Remove Account ────────────────────────────────────────────────────────────
async def cb_removeaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    acc = await db.get_account(user_id)
    if not acc:
        await q.message.reply_text(
            "ℹ️ No account linked to remove.",
            reply_markup=back_kb(),
        )
        return

    await q.message.reply_text(
        f"⚠️ *Remove Account*\n\n"
        f"{DIVIDER}\n"
        f"📱 Phone: `{acc['phone']}`\n\n"
        "This will log out your Telegram account from this bot.\n"
        "Your session file will be deleted.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🗑 Yes, Remove Account", callback_data="cb_removeaccount_confirm")],
            [_bbtn("🔙 Cancel", callback_data="cb_back")],
        ]),
    )


async def cb_removeaccount_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    # Stop any running campaign first so it never gets stuck
    await _clear_campaign_state(user_id)
    await userbot.logout_user(user_id)
    await db.remove_account(user_id)
    await q.message.reply_text(
        f"✅ *Account Removed*\n\n"
        f"{DIVIDER}\n"
        "Your Telegram account has been unlinked.\n"
        "Tap *Add Account* to link a different account.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


# ── Refer & Earn ───────────────────────────────────────────────────────────────
def _build_refer_message(user_id: int, referral_link: str, stats: dict, reward_days: int) -> str:
    completed = stats["completed"]
    milestone_days = db.get_milestone_total_days(completed)
    next_ms = db.get_next_milestone(completed)

    # Build milestone progress table
    milestones_text = ""
    for threshold, days in sorted(db.REFERRAL_MILESTONES.items()):
        if completed >= threshold:
            milestones_text += f"✅ {threshold} Referrals = {days} Day{'s' if days > 1 else ''}\n"
        else:
            milestones_text += f"⬜ {threshold} Referrals = {days} Day{'s' if days > 1 else ''}\n"

    # Next milestone progress bar
    next_ms_text = ""
    if next_ms:
        needed_threshold, needed_days = next_ms
        prev_threshold = max((t for t in db.REFERRAL_MILESTONES if t < needed_threshold), default=0)
        progress = completed - prev_threshold
        goal = needed_threshold - prev_threshold
        filled = round(10 * progress / goal) if goal else 10
        bar = "█" * filled + "░" * (10 - filled)
        next_ms_text = (
            f"\n🎯 *Next Milestone:* {needed_threshold} refs → {needed_days} days\n"
            f"`[{bar}]` {completed}/{needed_threshold}\n"
        )
    else:
        next_ms_text = "\n🏆 *All milestones reached!* Maximum rewards unlocked.\n"

    return (
        f"🔗 *REFER & EARN — Free Premium Days!*\n\n"
        f"{DIVIDER}\n"
        f"🎯 *Your Unique Referral Link:*\n"
        f"`{referral_link}`\n\n"
        f"📊 *Your Referral Stats:*\n"
        f"✅ Completed: *{completed}*\n"
        f"⏳ Pending:   *{stats['pending']}*\n"
        f"🎁 Milestone Days Earned: *{milestone_days} day(s)*\n"
        f"⭐ Per-Referral Bonus: *+{reward_days} day(s)* each\n\n"
        f"{DIVIDER}\n"
        f"🏅 *MILESTONE REWARDS:*\n\n"
        f"{milestones_text}"
        f"{next_ms_text}\n"
        f"{DIVIDER}\n"
        f"📋 *HOW IT WORKS:*\n\n"
        f"1️⃣ Share your link with a friend\n"
        f"2️⃣ They open the bot using YOUR link\n"
        f"3️⃣ They *add their Telegram account* ✅\n"
        f"4️⃣ They *run a DM campaign & send 1+ message* ✅\n\n"
        f"{DIVIDER}\n"
        f"⚠️ *RULES:*\n"
        f"• Opening the bot alone does NOT count\n"
        f"• Account + DM campaign — both required\n"
        f"• Cannot refer yourself\n"
        f"• Each person can only be referred once"
    )


async def cb_refer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = update.effective_user.id
    bot_username = BOT_USERNAME or "YourBot"
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    stats = await db.get_referrer_stats(user_id)
    reward_days = await db.get_referral_reward_days()

    msg = _build_refer_message(user_id, referral_link, stats, reward_days)

    kb = InlineKeyboardMarkup([
        [_gbtn("📤 Share My Referral Link", switch_inline_query=referral_link)],
        [_bbtn("🔙 Back to Menu", callback_data="cb_back")],
    ])
    await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def cmd_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Alias: /referral command shows the same refer & earn page."""
    user_id = update.effective_user.id
    bot_username = BOT_USERNAME or "YourBot"
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    stats = await db.get_referrer_stats(user_id)
    reward_days = await db.get_referral_reward_days()

    msg = _build_refer_message(user_id, referral_link, stats, reward_days)

    kb = InlineKeyboardMarkup([
        [_gbtn("📤 Share My Referral Link", switch_inline_query=referral_link)],
        [_bbtn("🏠 Back to Menu", callback_data="cb_back")],
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


# ── Channel Promo ─────────────────────────────────────────────────────────────
async def cb_channelpromo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _clear_user_convs(update)

    if not await ensure_not_banned(update):
        return ConversationHandler.END

    user = update.effective_user
    first = user.first_name or "there"

    intro = (
        f"👋 *Hey {first}! Welcome to Channel Promo!*\n\n"
        f"{DIVIDER}\n\n"
        "📣 *GROW YOUR CHANNEL AT 50% OFF*\n\n"
        "Want more members for your Telegram channel? You're in the right place! "
        "Through our *Channel Promo* service, we help you grow your channel by "
        "adding real members — and the best part? *You only pay half the market price.*\n\n"
        f"{DIVIDER}\n\n"
        "✨ *Why choose Channel Promo?*\n\n"
        "✅  *50% flat discount* on every order\n"
        "✅  Works with *public, private & join-request* channels\n"
        "✅  Both `t.me` and `telegram.me` invite links supported\n"
        "✅  Unique QR code generated per order — secure & trackable\n"
        "✅  Admin manually reviews every order for quality assurance\n"
        "✅  Instant notification the moment your order is approved\n\n"
        f"{DIVIDER}\n\n"
        "⚙️ *How it works — 4 simple steps:*\n\n"
        "1️⃣  Tell us the *current market price per member*\n"
        "      → We automatically cut it in half for you\n"
        "2️⃣  Send your *channel link*\n"
        "      → Public, private or join-request — all accepted\n"
        "3️⃣  Choose *how many members* you want\n"
        "      → Bot calculates your total at the discounted price\n"
        "4️⃣  Scan the *UPI QR code*, pay & submit your UTR\n"
        "      → Admin approves and your order is fulfilled ✅\n\n"
        f"{DIVIDER}\n\n"
        "🔗 *Supported link formats:*\n\n"
        "🔓 Public:   `@MyChannel`  ·  `t.me/MyChannel`\n"
        "🔒 Private:  `t.me/+Hash`  ·  `telegram.me/+Hash`\n"
        "🤝 Join-req: Any approval-gated invite link\n\n"
        f"{DIVIDER}\n\n"
        "💡 *Step 1 of 4 — Enter the market price per member:*\n\n"
        "What is the normal (full) price per member being charged elsewhere?\n"
        "Send *just the number* — e.g. `1`, `2`, `0.5`, `1.5`\n\n"
        "_We will instantly halve it and show your discounted rate before you continue._"
    )

    await q.message.reply_text(
        intro,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return CP_PRICE_INPUT


async def handle_cp_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("₹", "").replace(",", "").strip()
    try:
        market_price = float(text)
        if market_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ *Invalid price.* Please send a positive number only.\n\n"
            "Examples: `1`, `2.5`, `0.5`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[_rbtn("🔙 Cancel", callback_data="cb_back")]]),
        )
        return CP_PRICE_INPUT

    discounted = round(market_price / 2, 4)
    ctx.user_data["cp_price_per"] = discounted
    ctx.user_data["cp_market_price"] = market_price

    await update.message.reply_text(
        f"🎉 *Your 50% Discount Applied!*\n\n"
        f"{DIVIDER}\n"
        f"💰 Market price:     ~~₹{market_price:g}/member~~\n"
        f"✂️  Your price:       *₹{discounted:g}/member*\n"
        f"🏷️  Savings:          *50% off!*\n"
        f"{DIVIDER}\n\n"
        "🔗 *Step 2 of 4 — Send your channel link:*\n\n"
        "🔓 Public:   `@MyChannel`  ·  `t.me/MyChannel`\n"
        "🔒 Private:  `t.me/+Hash`  ·  `telegram.me/+Hash`\n"
        "🤝 Join-req: Any approval-gated invite link",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return CP_CHANNEL_INPUT


async def handle_cp_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    channel, label = _parse_channel_input(text)
    ctx.user_data["cp_channel"] = channel
    ctx.user_data["cp_label"] = label

    discounted = ctx.user_data.get("cp_price_per", 0)

    await update.message.reply_text(
        f"✅ *Channel link saved!*\n\n"
        f"{DIVIDER}\n"
        f"📣 Channel:     `{label}`\n"
        f"💰 Your price:  *₹{discounted:g}/member*\n"
        f"{DIVIDER}\n\n"
        "👥 *Step 3 of 4 — How many members do you want?*\n\n"
        "Send a whole number (e.g. `100`, `500`, `1000`, `5000`).\n"
        "The bot will calculate your total and show a payment QR instantly.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [_rbtn("🔙 Cancel", callback_data="cb_back")]
        ]),
    )
    return CP_MEMBER_COUNT


async def handle_cp_member_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace(" ", "")
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text(
            "⚠️ Please enter a valid whole number (e.g. `100`, `500`, `1000`).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[_rbtn("🔙 Cancel", callback_data="cb_back")]]),
        )
        return CP_MEMBER_COUNT

    member_count = int(text)
    discounted   = ctx.user_data.get("cp_price_per", 0)
    market_price = ctx.user_data.get("cp_market_price", discounted * 2)
    total_price  = round(discounted * member_count, 2)
    full_price   = round(market_price * member_count, 2)
    savings      = round(full_price - total_price, 2)
    order_id     = _generate_order_id()
    label        = ctx.user_data.get("cp_label", "your channel")
    channel      = ctx.user_data.get("cp_channel", "")

    ctx.user_data["cp_member_count"] = member_count
    ctx.user_data["cp_total"]        = total_price
    ctx.user_data["cp_order_id"]     = order_id

    upi = await db.get_setting("upi_id", UPI_ID)

    # Generate unique QR for this order
    qr_image = None
    try:
        import qr_utils
        qr_image = BytesIO(qr_utils.generate_upi_qr(upi, total_price, order_id))
    except Exception:
        qr_image = _get_bot_image("qr")

    caption = (
        f"💳 *CHANNEL PROMO — PAYMENT*\n\n"
        f"{DIVIDER}\n"
        f"🪪 Order ID:       `{order_id}`\n"
        f"📣 Channel:        `{label}`\n"
        f"👥 Members:        *{member_count:,}*\n"
        f"💰 Price/Member:   ₹{discounted:g} _(50% off ₹{market_price:g})_\n"
        f"💵 *Total:          ₹{total_price:g}*\n"
        f"🎁 You saved:      ₹{savings:g}\n"
        f"📲 UPI ID:         `{upi}`\n"
        f"{DIVIDER}\n\n"
        "📋 *Step 4 of 4 — Pay & submit your UTR:*\n\n"
        "1️⃣  Scan the QR code *or* open any UPI app\n"
        f"2️⃣  Pay exactly *₹{total_price:g}* to `{upi}`\n"
        "3️⃣  Copy your *UTR / Transaction ID* from the receipt\n"
        "4️⃣  Reply to this message with the UTR number\n\n"
        f"_Save Order ID `{order_id}` for any support queries._"
    )

    kb = InlineKeyboardMarkup([[_rbtn("🔙 Cancel", callback_data="cb_back")]])

    if qr_image is not None:
        try:
            await update.message.reply_photo(
                photo=qr_image, caption=caption,
                parse_mode="Markdown", reply_markup=kb,
            )
        except Exception:
            await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=kb)

    return CP_UTR_INPUT


async def handle_cp_utr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text.strip()
    user_id = update.effective_user.id
    user    = update.effective_user

    if not utr:
        await update.message.reply_text(
            "⚠️ Please send your UTR / Transaction ID.",
            reply_markup=InlineKeyboardMarkup([[_rbtn("🔙 Cancel", callback_data="cb_back")]]),
        )
        return CP_UTR_INPUT

    channel      = ctx.user_data.get("cp_channel", "")
    label        = ctx.user_data.get("cp_label", "your channel")
    member_count = ctx.user_data.get("cp_member_count", 0)
    discounted   = ctx.user_data.get("cp_price_per", 0)
    market_price = ctx.user_data.get("cp_market_price", discounted * 2)
    total_price  = ctx.user_data.get("cp_total", 0)
    order_id     = ctx.user_data.get("cp_order_id", _generate_order_id())

    # Persist order
    await db.create_promo_order(
        user_id=user_id,
        channel_link=channel,
        member_count=member_count,
        price_per_member=discounted,
        total_price=total_price,
        order_id=order_id,
    )
    await db.update_promo_order(order_id, utr=utr)

    # Notify admin
    if ADMIN_TG_ID:
        uname = f"@{user.username}" if user.username else "N/A"
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_TG_ID,
                text=(
                    f"🔔 *New Channel Promo Order*\n\n"
                    f"─────────────────────\n"
                    f"👤 User: `{user_id}` | {uname}\n"
                    f"🪪 Order ID: `{order_id}`\n"
                    f"📣 Channel: `{label}`\n"
                    f"👥 Members: *{member_count:,}*\n"
                    f"💰 Price/Member: ₹{discounted:g} (market ₹{market_price:g})\n"
                    f"💵 Total: ₹{total_price:g}\n"
                    f"🔖 UTR: `{utr}`\n"
                    f"─────────────────────\n\n"
                    "Open Admin Bot → *📣 Promo Orders* to approve or reject."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    support = await db.get_setting("support_username", ADMIN_USERNAME)
    await update.message.reply_text(
        f"🎉 *Order Placed Successfully!*\n\n"
        f"{DIVIDER}\n"
        f"🪪 Order ID:       `{order_id}`\n"
        f"📣 Channel:        `{label}`\n"
        f"👥 Members:        *{member_count:,}*\n"
        f"💵 Amount Paid:    ₹{total_price:g}\n"
        f"🔖 UTR:            `{utr}`\n"
        f"⏳ Status:         *Pending Review*\n"
        f"{DIVIDER}\n\n"
        "✅ Your order is in the queue! Our admin will verify your payment "
        "and process the order shortly.\n"
        "You will receive an *instant notification* here once your order is approved. 🚀\n\n"
        f"💬 Need help? Contact @{support}",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def cb_ownbot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer(
        url="https://t.me/shubhxseller?text=Hey%20Shubh%2C%20I%20want%20my%20own%20customized%20Auto%20DMs%20Bot.%20Let%27s%20discuss%20the%20pricing%20and%20other%20details."
    )


async def cancel_channelpromo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "❌ Channel Promo cancelled. Returning to menu.",
        reply_markup=main_menu_kb(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ── Global error handler ──────────────────────────────────────────────────────
async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception in update %s: %s", update, ctx.error, exc_info=ctx.error)
    # Try to notify the user if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong. Please try again or use /start.",
            )
        except Exception:
            pass


# ── App setup ─────────────────────────────────────────────────────────────────
def build_app():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    app.add_error_handler(_error_handler)

    add_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_addaccount, pattern="^cb_addaccount$")],
        states={
            ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_phone)],
            ADD_CODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_code)],
            ADD_2FA:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addaccount)],
        allow_reentry=True, per_message=False,
    )
    setmsg_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_setmsg, pattern="^cb_setmsg$")],
        states={
            SET_MSG_COLLECT: [
                CallbackQueryHandler(handle_msg_done, pattern="^msg_done$"),
                CallbackQueryHandler(cb_back, pattern="^cb_back$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_set_msg),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_setmsg)],
        allow_reentry=True, per_message=False,
    )
    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_ipaid, pattern="^ipaid_(?!auto_)")],
        states={
            PAY_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addaccount)],
        allow_reentry=True, per_message=False,
    )
    payment_auto_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_ipaid_auto, pattern="^ipaid_auto_")],
        states={
            PAY_UTR_AUTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr_auto)],
        },
        fallbacks=[CommandHandler("cancel", cancel_autopay)],
        allow_reentry=True, per_message=False,
    )
    giftcode_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_giftcode, pattern="^cb_giftcode$")],
        states={
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_code_input)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_giftcode),
            CallbackQueryHandler(cancel_giftcode, pattern="^cb_back$"),
        ],
        allow_reentry=True, per_message=False,
    )

    accept_pending_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_acceptpending, pattern="^cb_acceptpending$")],
        states={
            AP_CHANNEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ap_channel)],
            AP_COUNT_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ap_count)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_acceptpending),
            CallbackQueryHandler(cancel_acceptpending, pattern="^cb_back$"),
        ],
        allow_reentry=True, per_message=False,
    )

    joinrequestdm_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_joinrequestdm, pattern="^cb_joinrequestdm$")],
        states={
            JD_CHANNEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_jd_channel)],
            JD_COUNT_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_jd_count_input)],
            JD_MSG_INPUT:     [MessageHandler(filters.ALL & ~filters.COMMAND, handle_jd_message)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_joinrequestdm),
            CallbackQueryHandler(cancel_joinrequestdm, pattern="^cb_back$"),
        ],
        allow_reentry=True, per_message=False,
    )

    channelpromo_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_channelpromo, pattern="^cb_channelpromo$")],
        states={
            CP_PRICE_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cp_price)],
            CP_CHANNEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cp_channel)],
            CP_MEMBER_COUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cp_member_count)],
            CP_UTR_INPUT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cp_utr)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_channelpromo),
            CallbackQueryHandler(cancel_channelpromo, pattern="^cb_back$"),
        ],
        allow_reentry=True, per_message=False,
    )

    # ── Register all convs in module-level registry so _clear_user_convs works ──
    _all_convs.clear()
    _all_convs.extend([
        add_acc_conv, setmsg_conv, payment_conv, payment_auto_conv,
        giftcode_conv, accept_pending_conv, joinrequestdm_conv, channelpromo_conv,
    ])
    # camp_channel_conv added below after creation
    # ──────────────────────────────────────────────────────────────────────────

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(add_acc_conv)
    app.add_handler(setmsg_conv)
    app.add_handler(payment_conv)
    app.add_handler(payment_auto_conv)
    app.add_handler(giftcode_conv)
    app.add_handler(accept_pending_conv)
    app.add_handler(joinrequestdm_conv)
    app.add_handler(channelpromo_conv)

    camp_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_campaign_channel, pattern="^cb_campaign_channel$")],
        states={
            CAMP_CHANNEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_camp_channel)],
            CAMP_COUNT_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_camp_count)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_camp_channel),
            CallbackQueryHandler(cancel_camp_channel, pattern="^cb_back$"),
        ],
        allow_reentry=True, per_message=False,
    )
    _all_convs.append(camp_channel_conv)
    app.add_handler(camp_channel_conv)
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))
    app.add_handler(CommandHandler("referral", cmd_referral))
    app.add_handler(CallbackQueryHandler(cb_back, pattern="^cb_back$"))
    app.add_handler(CallbackQueryHandler(cb_tutorial, pattern="^cb_tutorial$"))
    app.add_handler(CallbackQueryHandler(cb_myaccount, pattern="^cb_myaccount$"))
    app.add_handler(CallbackQueryHandler(cb_stats, pattern="^cb_stats$"))
    app.add_handler(CallbackQueryHandler(cb_previewmsg, pattern="^cb_previewmsg$"))
    app.add_handler(CallbackQueryHandler(cb_premium, pattern="^cb_premium$"))
    app.add_handler(CallbackQueryHandler(cb_plan, pattern="^plan_"))
    app.add_handler(CallbackQueryHandler(cb_paymethod_admin, pattern="^paymethod_admin_"))
    app.add_handler(CallbackQueryHandler(cb_paymethod_auto, pattern="^paymethod_auto_"))
    app.add_handler(CallbackQueryHandler(cb_autopay_retry, pattern="^autopay_retry_"))
    app.add_handler(CallbackQueryHandler(cb_check_joined, pattern="^cb_check_joined$"))
    app.add_handler(CallbackQueryHandler(cb_campaign, pattern="^cb_campaign$"))
    app.add_handler(CallbackQueryHandler(cb_stop_campaign, pattern="^cb_stop_campaign$"))
    app.add_handler(CallbackQueryHandler(cb_removeaccount, pattern="^cb_removeaccount$"))
    app.add_handler(CallbackQueryHandler(cb_removeaccount_confirm, pattern="^cb_removeaccount_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_refer, pattern="^cb_refer$"))
    app.add_handler(CallbackQueryHandler(cb_ownbot, pattern="^cb_ownbot$"))

    return app
