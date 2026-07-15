"""
Launcher — validates environment variables, API credentials, initialises DB,
then runs both bots concurrently.

All configuration is read from environment variables (see config.py).
The bot will exit immediately with a clear error list if any required
variable is missing — there are no silent defaults.

concurrent_updates=True is set on both Application instances so that
100 simultaneous users are all served in parallel instead of sequentially.
"""
import asyncio
import logging

from telethon import TelegramClient
from telethon.errors import ApiIdInvalidError

# config.py validates all 9 required env vars and exits with a clear
# error message if any are missing — nothing below runs if that check fails.
import database as db
import bot as user_bot_module
import admin_bot as admin_bot_module
from config import API_ID, API_HASH, SESSIONS_DIR, GMAIL_ADDRESS, GMAIL_APP_PASSWORD

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def validate_api_credentials() -> bool:
    """
    Connect a temporary Telethon client to verify API_ID + API_HASH are valid.
    Returns True if valid, False (and logs the problem) if not.
    """
    import os, glob
    test_session = os.path.join(SESSIONS_DIR, "_cred_test")
    client = TelegramClient(test_session, API_ID, API_HASH)
    try:
        logger.info(f"Validating Telethon credentials (API_ID={API_ID})…")
        await client.connect()
        await client.get_me()
        logger.info("✅ API credentials are valid.")
        return True
    except ApiIdInvalidError:
        logger.error(
            "❌ TELEGRAM_API_ID / TELEGRAM_API_HASH are INVALID.\n"
            f"   API_ID in use : {API_ID}\n"
            "   Go to https://my.telegram.org → 'API development tools'\n"
            "   Copy the exact api_id (number) and api_hash (hex string)\n"
            "   and update your Railway environment variables."
        )
        return False
    except Exception as ex:
        logger.warning(f"Credential check skipped due to network/auth error: {ex}")
        return True
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        import glob, os as _os
        for f in glob.glob(test_session + "*"):
            try:
                _os.remove(f)
            except Exception:
                pass


async def main():
    # 1. Validate Telethon API credentials up-front
    ok = await validate_api_credentials()
    if not ok:
        logger.error(
            "Bots will still attempt to start but 'Add Account' will fail "
            "until TELEGRAM_API_ID / TELEGRAM_API_HASH are fixed in Railway."
        )

    # 2. Initialise DB tables before either bot starts handling updates
    await db.init_db()
    logger.info("Database initialised.")

    # 3. Seed Gmail credentials into gmail_checker.
    #    Priority order:
    #      a) DB-saved value (admin changed it via Admin Bot)  ← highest
    #      b) Environment variable (Railway config)            ← fallback
    import gmail_checker
    saved_gmail      = await db.get_setting("gmail_address",      "")
    saved_gmail_pass = await db.get_setting("gmail_app_password", "")

    gmail_checker.GMAIL_ADDRESS      = saved_gmail      or GMAIL_ADDRESS
    gmail_checker.GMAIL_APP_PASSWORD = saved_gmail_pass or GMAIL_APP_PASSWORD

    if gmail_checker.GMAIL_ADDRESS and gmail_checker.GMAIL_APP_PASSWORD:
        logger.info(
            f"✅ Gmail auto-verification ready → {gmail_checker.GMAIL_ADDRESS}"
            + (" (overridden from DB)" if saved_gmail else " (from env var)")
        )
    else:
        logger.warning(
            "⚠️  Gmail credentials are not configured. "
            "Automatic payment verification will not work. "
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Railway variables."
        )

    # 4. Load custom buttons and plans into the user bot's in-memory cache
    await user_bot_module.reload_custom_buttons()
    logger.info("Custom buttons loaded.")
    await user_bot_module.reload_plans()
    logger.info("Plans loaded.")

    # 5. Build and start both bots
    user_app  = user_bot_module.build_app()
    admin_app = admin_bot_module.build_app()

    await user_app.initialize()
    await admin_app.initialize()

    await user_app.start()
    await admin_app.start()

    await user_app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )
    await admin_app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    logger.info(
        "✅ Both bots running with concurrent_updates=True — "
        "all users served in parallel."
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down…")
        await user_app.updater.stop()
        await admin_app.updater.stop()
        await user_app.stop()
        await admin_app.stop()
        await user_app.shutdown()
        await admin_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
