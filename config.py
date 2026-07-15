"""
Central configuration — all values come from environment variables.

REQUIRED variables (bot will refuse to start if any are missing):
  TELEGRAM_BOT_TOKEN      User-facing bot token from @BotFather
  ADMIN_BOT_TOKEN         Admin bot token from @BotFather
  TELEGRAM_API_ID         Integer API ID from https://my.telegram.org
  TELEGRAM_API_HASH       API hash string from https://my.telegram.org
  ADMIN_TG_ID             Your Telegram numeric user ID (admin)
  UPI_ID                  UPI payment address (e.g. yourname@upi)
  BOT_USERNAME            Username of the user bot (without @)
  GMAIL_ADDRESS           Gmail address that receives UPI payment receipts
  GMAIL_APP_PASSWORD      Gmail App Password (16-char code from Google)

Set these in Railway → your service → Variables before deploying.
"""
import os
import sys

# ── Collect all 9 required variables ──────────────────────────────────────────

# ── 7 variables that are critical for the bots to run at all ──────────────────
_REQUIRED: list[tuple[str, str]] = [
    ("TELEGRAM_BOT_TOKEN", "User-facing bot token from @BotFather"),
    ("ADMIN_BOT_TOKEN",    "Admin bot token from @BotFather"),
    ("TELEGRAM_API_ID",    "Integer API ID from https://my.telegram.org"),
    ("TELEGRAM_API_HASH",  "API hash string from https://my.telegram.org"),
    ("ADMIN_TG_ID",        "Your Telegram numeric user ID (admin)"),
    ("UPI_ID",             "UPI payment address, e.g. yourname@upi"),
    ("BOT_USERNAME",       "Username of the user bot (without @)"),
]

_missing: list[str] = []
for _key, _desc in _REQUIRED:
    if not os.environ.get(_key, "").strip():
        _missing.append(f"  ❌  {_key:30s}  ←  {_desc}")

if _missing:
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════════╗\n"
        "║       MISSING REQUIRED ENVIRONMENT VARIABLES                    ║\n"
        "╚══════════════════════════════════════════════════════════════════╝\n"
        "\n"
        "The following variables must be set before the bot can start.\n"
        "In Railway: open your service → Variables → add each one below.\n"
        "\n"
        + "\n".join(_missing)
        + "\n\n"
        "Bot cannot start until all variables are configured. Exiting.\n",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Gmail (optional — auto-payment verification only) ─────────────────────────
# The bots run without these; only the automatic UTR/payment verification
# feature requires them.  A warning is printed at startup if they are absent.
_gmail_missing: list[str] = []
for _key, _desc in [
    ("GMAIL_ADDRESS",      "Gmail address that receives UPI payment receipts"),
    ("GMAIL_APP_PASSWORD", "Gmail App Password — Google Account → Security → App Passwords"),
]:
    if not os.environ.get(_key, "").strip():
        _gmail_missing.append(f"  ⚠️   {_key:30s}  ←  {_desc}")

if _gmail_missing:
    print(
        "\n"
        "⚠️  Gmail credentials not set — automatic payment verification is DISABLED.\n"
        "   Set these in Railway Variables to enable it:\n"
        + "\n".join(_gmail_missing)
        + "\n",
        file=sys.stderr,
    )

# ── All variables present — load them ─────────────────────────────────────────

BOT_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"].strip()
ADMIN_BOT_TOKEN = os.environ["ADMIN_BOT_TOKEN"].strip()
API_HASH        = os.environ["TELEGRAM_API_HASH"].strip()
BOT_USERNAME    = os.environ["BOT_USERNAME"].strip()
UPI_ID          = os.environ["UPI_ID"].strip()

# Gmail credentials for automatic UPI payment verification (optional)
GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS",      "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

# Integer fields — validated here so errors surface early with clear messages
try:
    API_ID = int(os.environ["TELEGRAM_API_ID"].strip())
except ValueError:
    print(
        "❌  TELEGRAM_API_ID must be a plain integer (e.g. 12345678).\n"
        f"   Got: {os.environ['TELEGRAM_API_ID']!r}\n"
        "   Find the correct value at https://my.telegram.org",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    ADMIN_TG_ID = int(os.environ["ADMIN_TG_ID"].strip())
except ValueError:
    print(
        "❌  ADMIN_TG_ID must be a plain integer Telegram user ID.\n"
        f"   Got: {os.environ['ADMIN_TG_ID']!r}\n"
        "   Send /start to @userinfobot on Telegram to find your numeric ID.",
        file=sys.stderr,
    )
    sys.exit(1)

# Kept for backwards-compat but no longer used (admin is set via ADMIN_TG_ID)
ADMIN_USERNAME = "shubhxseller"

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(__file__)
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
DATA_DIR   = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

WELCOME_IMAGE = os.path.join(ASSETS_DIR, "welcome.jpg")
QR_IMAGE      = os.path.join(ASSETS_DIR, "payment_qr.jpg")

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(DATA_DIR,     exist_ok=True)

# ── Default plan & limit values (editable from Admin Bot at runtime) ───────────

FREE_DM_LIMIT    = 100
FREE_ACCEPT_LIMIT = 20   # free users: max join requests accepted per action

PLANS = {
    "1d":  {"label": "1 Day",   "days": 1,  "price": 10},
    "3d":  {"label": "3 Days",  "days": 3,  "price": 30},
    "7d":  {"label": "7 Days",  "days": 7,  "price": 60},
    "15d": {"label": "15 Days", "days": 15, "price": 100},
    "1m":  {"label": "1 Month", "days": 30, "price": 190},
}

TUTORIAL_TEXT = (
    "📖 *Tutorial & Terms*\n\n"
    "*How to Login:*\n"
    "Step 1 — Enter your phone number with country code (e.g. +91XXXXXXXXXX)\n"
    "Step 2 — Enter the OTP sent to your Telegram\n"
    "Step 3 — Enter your 2FA password (if set)\n"
    "Your account will be added after these steps.\n\n"
    "*How to Use:*\n"
    "Step 1 — Go to *Set Message* and enter the message/link/image you want to send\n"
    "Step 2 — Tap *Start Mass Campaign* — the bot will send your message to all DMs and chats\n\n"
    "*Free Plan Limits:*\n"
    "After adding your account, you can send up to *100 DMs and 100 group chats* for free.\n"
    "After that, you must purchase a premium plan to continue.\n\n"
    "*Premium Plans:*\n"
    "Once the admin approves your payment, you get *unlimited sends* for the plan duration.\n\n"
    "*Terms:*\n"
    "• Do not use this bot for spam or illegal activity.\n"
    "• The team is not responsible for misuse.\n"
    "• Premium plans are non-refundable.\n"
    "• By using this bot, you agree to these terms.\n\n"
    "👤 Support: @shubhxseller"
)
