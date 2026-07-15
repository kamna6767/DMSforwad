"""
Admin bot — fully advanced dashboard, settings panel, and management tools.
"""
import asyncio
import logging
import secrets
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=UserWarning)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

import database as db
import bot as user_bot_module
from config import ADMIN_BOT_TOKEN, ADMIN_TG_ID, PLANS, ADMIN_USERNAME, UPI_ID

logger = logging.getLogger(__name__)

DIVIDER = "─" * 22

# ── States ────────────────────────────────────────────────────────────────────
(
    BAN_INPUT, UNBAN_INPUT,
    GIFT_DAYS_INPUT, GIFT_CODE_INPUT,
    BROADCAST_INPUT,
    BROADCAST_CONFIRM,
    MAINTENANCE_INPUT,
    EDIT_CHANNEL_ADD_INPUT,
    EDIT_SUPPORT_INPUT,
    EDIT_UPI_INPUT,
    EDIT_ADMIN_ADD_INPUT,
    EDIT_ADMIN_REMOVE_INPUT,
    EDIT_WELCOME_INPUT,
    USER_SEARCH_INPUT,
    GIFT_MAXUSES_INPUT,
    CUSTOM_BTN_LABEL_INPUT,
    CUSTOM_BTN_URL_INPUT,
    SET_PRICE_EDIT_INPUT,
    SET_PRICE_NEW_DAYS_INPUT,
    SET_PRICE_NEW_PRICE_INPUT,
    REFERRAL_REWARD_INPUT,
    FREE_LIMIT_INPUT,
    MSG_USER_UID_INPUT,
    MSG_USER_BODY_INPUT,
    EXTEND_PREM_DAYS_INPUT,
    BOT_NAME_INPUT,
    UPLOAD_WELCOME_IMG,
    UPLOAD_QR_IMG,
    WATERMARK_USERNAME_INPUT,
    GMAIL_EMAIL_INPUT,
    GMAIL_PASS_INPUT,
    PROMO_PRICE_INPUT,
    SET_UPI_SETTINGS_INPUT,
) = range(33)


# ── Auth ──────────────────────────────────────────────────────────────────────
def is_primary_admin(user_id: int) -> bool:
    return ADMIN_TG_ID != 0 and user_id == ADMIN_TG_ID


async def admin_only(update: Update) -> bool:
    uid = update.effective_user.id
    if is_primary_admin(uid):
        return True
    if await db.is_extra_admin(uid):
        return True
    await update.effective_message.reply_text("🚫 *Unauthorised access.*", parse_mode="Markdown")
    return False


# ── Dashboard builder ─────────────────────────────────────────────────────────
async def _build_dashboard() -> str:
    users = await db.get_all_users()
    payments = await db.get_all_payments()
    approved = [p for p in payments if p["status"] == "approved"]
    pending = [p for p in payments if p["status"] == "pending"]
    banned = [u for u in users if u.get("is_banned")]
    revenue = sum(p["amount"] for p in approved)
    channels = await db.get_force_join_channels()
    admins = await db.get_extra_admins()
    premium_users = await db.get_all_premium_users()
    accounts_count = await db.get_accounts_count()
    total_dms = await db.get_total_dms_sent()
    new_today = await db.get_new_users_today()
    active_camps = await db.get_active_campaigns_count()
    free_limit = await db.get_free_limit()

    alert = ""
    if pending:
        alert = f"\n🔔 *{len(pending)} payment(s) need your review!*"

    return (
        f"🛠 *ADMIN DASHBOARD*\n"
        f"{DIVIDER}\n"
        f"👥 Total Users: *{len(users)}*  (+{new_today} today)\n"
        f"👑 Active Premium: *{len(premium_users)}*\n"
        f"📱 Accounts Linked: *{accounts_count}*\n"
        f"🚫 Banned: *{len(banned)}*  |  🔑 Admins: *{len(admins)}*\n\n"
        f"📨 *ACTIVITY*\n"
        f"{DIVIDER}\n"
        f"✉️ Total DMs Sent: *{total_dms:,}*\n"
        f"🔄 Active Campaigns: *{active_camps}*\n\n"
        f"💰 *PAYMENTS*\n"
        f"{DIVIDER}\n"
        f"✅ Approved: *{len(approved)}*  |  ⏳ Pending: *{len(pending)}*\n"
        f"💵 Total Revenue: *₹{revenue:,}*\n\n"
        f"⚙️ *SETTINGS*\n"
        f"{DIVIDER}\n"
        f"📣 Force Channels: *{len(channels)}*  |  🆓 Free Limit: *{free_limit} DMs*\n"
        f"{alert}"
    )


# ── Keyboards ─────────────────────────────────────────────────────────────────
def admin_menu_kb():
    return InlineKeyboardMarkup([
        # ── Users ──────────────────────────────────────────────
        [InlineKeyboardButton("👥 All Users", callback_data="a_users"),
         InlineKeyboardButton("🔍 Search User", callback_data="a_search")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="a_ban"),
         InlineKeyboardButton("✅ Unban User", callback_data="a_unban")],
        # ── Payments ───────────────────────────────────────────
        [InlineKeyboardButton("⏳ Pending Payments", callback_data="a_pending"),
         InlineKeyboardButton("💰 All Payments", callback_data="a_allpayments")],
        [InlineKeyboardButton("📊 Revenue Stats", callback_data="a_revenue"),
         InlineKeyboardButton("💳 UPI Settings", callback_data="a_upi_settings")],
        [InlineKeyboardButton("📧 Gmail Settings", callback_data="a_gmail_settings")],
        # ── Messaging ──────────────────────────────────────────
        [InlineKeyboardButton("📢 Broadcast", callback_data="a_broadcast"),
         InlineKeyboardButton("✉️ Message User", callback_data="a_msguser")],
        # ── Premium & Analytics ────────────────────────────────
        [InlineKeyboardButton("👑 Premium Users", callback_data="a_premiumusers"),
         InlineKeyboardButton("🎁 Gift Code", callback_data="a_gift")],
        [InlineKeyboardButton("📈 Analytics", callback_data="a_analytics"),
         InlineKeyboardButton("💰 Set Price", callback_data="a_set_price")],
        # ── Bot Config ─────────────────────────────────────────
        [InlineKeyboardButton("🔗 Custom Buttons", callback_data="a_custom_buttons"),
         InlineKeyboardButton("🤝 Referral Settings", callback_data="a_referral")],
        [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings"),
         InlineKeyboardButton("⚙️ Edit / Settings", callback_data="a_edit")],
        # ── System ─────────────────────────────────────────────
        [InlineKeyboardButton("🔧 Maintenance Mode", callback_data="a_maintenance"),
         InlineKeyboardButton("📱 Linked Users", callback_data="a_linked_users")],
        # ── Channel Promo ──────────────────────────────────────────────
        [InlineKeyboardButton("📣 Promo Orders", callback_data="a_promo_orders"),
         InlineKeyboardButton("💸 Set Promo Price/Member", callback_data="a_set_promo_price")],
        # ── Help ───────────────────────────────────────────────
        [InlineKeyboardButton("📖 How to Use (Admin Guide)", callback_data="a_howto")],
        [InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="a_refresh")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")]])


def edit_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 Force Join Channels", callback_data="ae_channels")],
        [InlineKeyboardButton("👤 Support Username", callback_data="ae_support"),
         InlineKeyboardButton("💳 UPI ID", callback_data="ae_upi")],
        [InlineKeyboardButton("👑 Add Admin", callback_data="ae_admin_add"),
         InlineKeyboardButton("🗑 Remove Admin", callback_data="ae_admin_remove")],
        [InlineKeyboardButton("📋 View All Admins", callback_data="ae_admin_list")],
        [InlineKeyboardButton("📝 Edit Welcome Text", callback_data="ae_welcome")],
        [InlineKeyboardButton("🖼 Change Welcome Image", callback_data="ae_welcome_img"),
         InlineKeyboardButton("📷 Change QR Image", callback_data="ae_qr_img")],
        [InlineKeyboardButton("🔙 Back", callback_data="a_back")],
    ])


def channels_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel", callback_data="ae_channel_add")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="ae_channel_remove")],
        [InlineKeyboardButton("🔙 Back", callback_data="a_edit")],
    ])


def gift_days_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 1 Day", callback_data="giftday_1"),
         InlineKeyboardButton("🔥 3 Days", callback_data="giftday_3")],
        [InlineKeyboardButton("💎 7 Days", callback_data="giftday_7"),
         InlineKeyboardButton("🏆 15 Days", callback_data="giftday_15")],
        [InlineKeyboardButton("👑 1 Month", callback_data="giftday_30"),
         InlineKeyboardButton("♾️ Unlimited", callback_data="giftday_999")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="a_back")],
    ])


def payment_action_kb(payment_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{payment_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_{payment_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="a_back")],
    ])


def promo_order_action_kb(order_id: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"promo_approve_{order_id}"),
         InlineKeyboardButton("❌ Reject",  callback_data=f"promo_reject_{order_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="a_back")],
    ])


# ── /start — Live Dashboard ───────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    dash = await _build_dashboard()
    await update.message.reply_text(
        dash, parse_mode="Markdown", reply_markup=admin_menu_kb())


async def cb_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    dash = await _build_dashboard()
    await q.message.reply_text(
        dash, parse_mode="Markdown", reply_markup=admin_menu_kb())


async def cb_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Refreshing…")
    if not await admin_only(update):
        return
    dash = await _build_dashboard()
    try:
        await q.message.edit_text(dash, parse_mode="Markdown", reply_markup=admin_menu_kb())
    except Exception:
        await q.message.reply_text(dash, parse_mode="Markdown", reply_markup=admin_menu_kb())


# ── Edit / Settings ───────────────────────────────────────────────────────────
async def cb_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    support = await db.get_setting("support_username", ADMIN_USERNAME)
    upi = await db.get_setting("upi_id", UPI_ID)
    channels = await db.get_force_join_channels()
    ch_text = ", ".join(f"@{c}" for c in channels) or "None"
    await q.message.reply_text(
        f"⚙️ *SETTINGS PANEL*\n"
        f"{DIVIDER}\n"
        f"📣 Force Channels: `{ch_text}`\n"
        f"👤 Support: @{support}\n"
        f"💳 UPI ID: `{upi}`\n"
        f"{DIVIDER}\n\n"
        "Select what to edit 👇",
        parse_mode="Markdown",
        reply_markup=edit_menu_kb(),
    )


# ── Force Join Channels ───────────────────────────────────────────────────────
def _channel_display_label(ch: str) -> str:
    """Human-readable label for a channel entry (public or private)."""
    if db._is_private_channel_link(ch):
        return f"🔒 Private: {ch}"
    return f"📣 @{ch}"


async def cb_edit_channels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    channels = await db.get_force_join_channels()
    ch_text = "\n".join(f"  • {_channel_display_label(c)}" for c in channels) or "  None set yet."
    await q.message.reply_text(
        f"📣 *FORCE JOIN CHANNELS*\n"
        f"{DIVIDER}\n"
        f"Users must join these channels before using the bot:\n\n"
        f"{ch_text}\n\n"
        "Choose an action 👇",
        parse_mode="Markdown",
        reply_markup=channels_menu_kb(),
    )


async def cb_channel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"➕ *Add Force Join Channel*\n\n"
        f"{DIVIDER}\n"
        "Send one of the following:\n\n"
        "📣 *Public channel* — username (with or without @):\n"
        "   `MyPublicChannel`\n\n"
        "🔒 *Private channel* — the invite link:\n"
        "   `https://t.me/+AbCdEfGhIjK`\n\n"
        "For public channels the bot must be an admin to verify membership.\n"
        "For private channels users confirm on their honour (tap I've Joined).\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="ae_channels")]]),
    )
    return EDIT_CHANNEL_ADD_INPUT


async def handle_channel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    channel = db.normalize_channel_input(raw)
    channels = await db.add_force_join_channel(channel)
    label = _channel_display_label(channel)
    ch_list = "\n".join(f"  • {_channel_display_label(c)}" for c in channels)
    await update.message.reply_text(
        f"✅ *Added!*\n\n"
        f"Entry: {label}\n\n"
        f"All force-join channels:\n{ch_list}",
        parse_mode="Markdown",
        reply_markup=edit_menu_kb(),
    )
    return ConversationHandler.END


async def cb_channel_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    channels = await db.get_force_join_channels()
    if not channels:
        await q.message.reply_text("No channels to remove.", reply_markup=channels_menu_kb())
        return
    # Use index-based callbacks — private invite links can exceed callback_data limits
    rows = [
        [InlineKeyboardButton(f"🗑 {_channel_display_label(c)}", callback_data=f"ae_rmch_{i}")]
        for i, c in enumerate(channels)
    ]
    rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="ae_channels")])
    await q.message.reply_text(
        "➖ *Remove a Channel*\n\nTap the one to remove:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cb_channel_remove_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    try:
        index = int(q.data.replace("ae_rmch_", ""))
    except (ValueError, TypeError):
        await q.message.reply_text("⚠️ Invalid selection.", reply_markup=edit_menu_kb())
        return ConversationHandler.END
    # Snapshot name before removing
    channels_before = await db.get_force_join_channels()
    removed_label = _channel_display_label(channels_before[index]) if index < len(channels_before) else "Unknown"
    channels = await db.remove_force_join_channel_by_index(index)
    ch_list = "\n".join(f"  • {_channel_display_label(c)}" for c in channels) or "  None"
    await q.message.reply_text(
        f"✅ *Removed:* {removed_label}\n\n"
        f"Remaining channels:\n{ch_list}",
        parse_mode="Markdown", reply_markup=edit_menu_kb(),
    )


# ── Support Username ──────────────────────────────────────────────────────────
async def cb_edit_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("support_username", ADMIN_USERNAME)
    await q.message.reply_text(
        f"👤 *Change Support Username*\n\n"
        f"Current: @{current}\n\n"
        "Send the new username (with or without @):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return EDIT_SUPPORT_INPUT


async def handle_support_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    username = update.message.text.strip().lstrip("@")
    await db.set_setting("support_username", username)
    await update.message.reply_text(
        f"✅ Support username → @{username}", parse_mode="Markdown", reply_markup=edit_menu_kb())
    return ConversationHandler.END


# ── UPI ID ────────────────────────────────────────────────────────────────────
async def cb_edit_upi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("upi_id", UPI_ID)
    await q.message.reply_text(
        f"💳 *Change UPI ID*\n\nCurrent: `{current}`\n\nSend the new UPI ID:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return EDIT_UPI_INPUT


async def handle_upi_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler for UPI ID input coming from the Edit / Settings menu (ae_upi path)."""
    if not await admin_only(update):
        return ConversationHandler.END
    upi = update.message.text.strip()

    import qr_utils as _qr
    valid, err = _qr.validate_upi_id(upi)
    if not valid:
        await update.message.reply_text(
            f"⚠️ *Invalid UPI ID*\n\n{err}\n\nPlease send a valid UPI ID:",
            parse_mode="Markdown",
        )
        return EDIT_UPI_INPUT

    await db.set_setting("upi_id", upi)

    # Generate a live QR preview to confirm it's working
    qr_bytes = None
    try:
        from io import BytesIO
        qr_bytes = BytesIO(_qr.generate_upi_qr(upi, 1, "PREVIEW"))
    except Exception:
        pass

    success_text = (
        f"✅ *UPI ID Updated!*\n\n"
        f"{DIVIDER}\n"
        f"📲 New UPI ID:\n`{upi}`\n"
        f"{DIVIDER}\n\n"
        "QR preview above is for ₹1. Every user order will get a\n"
        "*unique QR with the exact order amount* automatically."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 UPI Settings", callback_data="a_upi_settings")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])
    if qr_bytes:
        try:
            await update.message.reply_photo(
                photo=qr_bytes, caption=success_text,
                parse_mode="Markdown", reply_markup=kb,
            )
            return ConversationHandler.END
        except Exception:
            pass
    await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END


# ── Set UPI ID from UPI Settings screen ───────────────────────────────────────
async def cb_set_upi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry: admin taps 'Set UPI ID' from the UPI Settings screen."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("upi_id", UPI_ID)
    await q.message.reply_text(
        f"💳 *Set UPI ID*\n\n"
        f"{DIVIDER}\n"
        f"Current UPI ID:\n`{current}`\n"
        f"{DIVIDER}\n\n"
        "Send the new UPI ID.\n"
        "📌 Format: `localpart@provider`\n"
        "Examples: `9876543210@paytm` · `yourname@upi` · `shop@okicici`\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="a_upi_settings")]
        ]),
    )
    return SET_UPI_SETTINGS_INPUT


async def handle_set_upi_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Validate the UPI ID, save it, show a live QR preview, return to UPI Settings."""
    if not await admin_only(update):
        return ConversationHandler.END
    upi = update.message.text.strip()

    import qr_utils as _qr
    from io import BytesIO

    valid, err = _qr.validate_upi_id(upi)
    if not valid:
        await update.message.reply_text(
            f"⚠️ *Invalid UPI ID*\n\n{err}\n\n"
            "Please send a valid UPI ID, or /cancel to abort.",
            parse_mode="Markdown",
        )
        return SET_UPI_SETTINGS_INPUT

    await db.set_setting("upi_id", upi)

    # Generate a live QR preview for ₹1 so the admin can instantly verify it scans
    qr_bytes = None
    try:
        bot_name = await db.get_setting("bot_name", "AutoDMs Bot")
        qr_bytes = BytesIO(_qr.generate_upi_qr(upi, 1, "PREVIEW", merchant_name=bot_name))
    except Exception:
        pass

    success_text = (
        f"✅ *UPI ID Saved Successfully!*\n\n"
        f"{DIVIDER}\n"
        f"📲 UPI ID: `{upi}`\n"
        f"{DIVIDER}\n\n"
        "✔️ The QR above is a live preview for ₹1 — scan it to verify.\n"
        "✔️ Every user order will automatically get a *unique QR* with\n"
        "   the exact order amount embedded.\n"
        "✔️ Payments go directly to your UPI ID."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 View UPI Settings", callback_data="a_upi_settings")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])

    if qr_bytes:
        try:
            await update.message.reply_photo(
                photo=qr_bytes,
                caption=success_text,
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return ConversationHandler.END
        except Exception:
            pass

    await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END


# ── Add Admin ─────────────────────────────────────────────────────────────────
async def cb_edit_admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"👑 *Add New Admin*\n\n"
        f"{DIVIDER}\n"
        "Send the Telegram *User ID* of the new admin.\n"
        "Example: `123456789`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return EDIT_ADMIN_ADD_INPUT


async def handle_admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    try:
        new_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ Invalid user ID.", reply_markup=edit_menu_kb())
        return ConversationHandler.END
    if new_id == ADMIN_TG_ID:
        await update.message.reply_text("⚠️ That's already the primary admin.", reply_markup=edit_menu_kb())
        return ConversationHandler.END
    await db.add_extra_admin(new_id, update.effective_user.id)
    try:
        await ctx.bot.send_message(chat_id=new_id,
            text="🎉 *You've been made an admin* of Auto DMs Bot!\n\nYou now have full admin access.",
            parse_mode="Markdown")
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ *Admin added!*\nUser ID `{new_id}` now has admin access.",
        parse_mode="Markdown", reply_markup=edit_menu_kb())
    return ConversationHandler.END


# ── Remove Admin ──────────────────────────────────────────────────────────────
async def cb_edit_admin_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    admins = await db.get_extra_admins()
    if not admins:
        await q.message.reply_text("No extra admins to remove.", reply_markup=edit_menu_kb())
        return
    rows = [[InlineKeyboardButton(f"🗑 ID: {a['user_id']}", callback_data=f"ae_rmadmin_{a['user_id']}")] for a in admins]
    rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")])
    await q.message.reply_text("🗑 *Remove Admin*\n\nTap to remove:", parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(rows))


async def cb_admin_remove_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    admin_id = int(q.data.replace("ae_rmadmin_", ""))
    await db.remove_extra_admin(admin_id)
    try:
        await ctx.bot.send_message(chat_id=admin_id, text="ℹ️ Your admin access has been removed.")
    except Exception:
        pass
    await q.message.reply_text(
        f"✅ Admin `{admin_id}` removed.", parse_mode="Markdown", reply_markup=edit_menu_kb())


async def cb_admin_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    admins = await db.get_extra_admins()
    lines = [f"👑 *Primary:* `{ADMIN_TG_ID}`"]
    for a in admins:
        lines.append(f"🔑 `{a['user_id']}` — added {str(a['added_at'])[:10]}")
    await q.message.reply_text(
        f"📋 *ALL ADMINS*\n{DIVIDER}\n" + "\n".join(lines),
        parse_mode="Markdown", reply_markup=edit_menu_kb())


# ── Welcome Text ──────────────────────────────────────────────────────────────
async def cb_edit_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("welcome_text", "")
    preview = (current[:150] + "…") if len(current) > 150 else (current or "_default_")
    await q.message.reply_text(
        f"📝 *Edit Welcome Text*\n\n"
        f"Current:\n_{preview}_\n\n"
        "Send the new welcome message:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return EDIT_WELCOME_INPUT


async def handle_welcome_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    await db.set_setting("welcome_text", update.message.text.strip())
    await update.message.reply_text("✅ Welcome text updated!", reply_markup=edit_menu_kb())
    return ConversationHandler.END


# ── All Users ─────────────────────────────────────────────────────────────────
async def cb_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    users = await db.get_all_users()
    if not users:
        await q.message.reply_text("No users yet.", reply_markup=back_kb())
        return

    chunks = []
    chunk = f"👥 *ALL USERS ({len(users)} total)*\n{DIVIDER}\n"
    for u in users:
        status = "🚫" if u.get("is_banned") else "✅"
        line = (
            f"{status} `{u['user_id']}` | @{u.get('username') or 'N/A'} | "
            f"📱 {u.get('phone') or 'N/A'} | "
            f"🗓 {str(u.get('created_at', ''))[:10]}\n"
        )
        if len(chunk) + len(line) > 3800:
            chunks.append(chunk)
            chunk = ""
        chunk += line
    if chunk:
        chunks.append(chunk)
    for c in chunks:
        await q.message.reply_text(c, parse_mode="Markdown", reply_markup=back_kb())


# ── Search User ───────────────────────────────────────────────────────────────
async def cb_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"🔍 *Search User*\n\n{DIVIDER}\n"
        "Enter a *User ID* or *@username* to look up:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]),
    )
    return USER_SEARCH_INPUT


async def handle_user_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    target = update.message.text.strip().lstrip("@")
    users = await db.get_all_users()
    found = next((u for u in users if str(u["user_id"]) == target or u.get("username") == target), None)
    if not found:
        await update.message.reply_text(
            "❌ User not found.", reply_markup=back_kb())
        return ConversationHandler.END

    uid = found["user_id"]
    stats = await db.get_stats(uid) or {}
    prem = await db.get_premium(uid)
    is_active = await db.check_premium_active(uid)
    camp = await db.get_campaign(uid)

    free_limit = await db.get_free_limit()
    if is_active and prem:
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(prem["expires_at"])
            from datetime import timezone as _tz
            diff = max(0, (exp - _dt.now(_tz.utc).replace(tzinfo=None)).days)
            plan_line = f"👑 Premium — `{prem['plan_key']}` | expires `{prem['expires_at'][:10]}` | {diff}d left"
        except Exception:
            plan_line = f"👑 Premium — `{prem['plan_key']}`"
    else:
        used = stats.get("total_sent", 0)
        remaining = max(0, free_limit - used)
        plan_line = f"🆓 Free — {used}/{free_limit} used  ({remaining} remaining)"

    last_camp = "None"
    if camp:
        status_icon = {"done": "✅", "running": "🔄", "cancelled": "⛔", "error": "❌"}.get(camp["status"], "•")
        last_camp = f"{status_icon} {camp['status']} — {camp['sent']}/{camp['total']}"

    acc = await db.get_account(uid)
    referrals = await db.get_referrer_stats(uid)

    msg = (
        f"👤 *USER DETAILS*\n"
        f"{DIVIDER}\n"
        f"🆔 User ID: `{uid}`\n"
        f"👤 Username: @{found.get('username') or 'N/A'}\n"
        f"📱 Phone: `{acc['phone'] if acc else found.get('phone') or 'N/A'}`\n"
        f"📅 Joined: `{str(found.get('created_at', ''))[:10]}`\n"
        f"🚫 Banned: {'Yes 🚫' if found.get('is_banned') else 'No ✅'}\n\n"
        f"💎 *PLAN*\n{DIVIDER}\n{plan_line}\n\n"
        f"📊 *STATS*\n{DIVIDER}\n"
        f"📨 Total DMs Sent: *{stats.get('total_sent', 0):,}*\n"
        f"💰 Plans Bought: *{stats.get('plans_bought', 0)}*\n"
        f"🤝 Referrals: *{referrals['completed']}* completed / *{referrals['pending']}* pending\n"
        f"🎯 Last Campaign: {last_camp}\n"
    )
    ban_label = "✅ Unban" if found.get("is_banned") else "🚫 Ban"
    ban_cb = f"a_quickunban_{uid}" if found.get("is_banned") else f"a_quickban_{uid}"

    rows = [
        [InlineKeyboardButton(ban_label, callback_data=ban_cb),
         InlineKeyboardButton("🎁 Gift Premium", callback_data=f"a_giftuser_{uid}")],
        [InlineKeyboardButton("✉️ Message User", callback_data=f"a_msgtarget_{uid}"),
         InlineKeyboardButton("🔄 Reset Sends", callback_data=f"a_resetsends_{uid}")],
    ]
    if is_active:
        rows.append([
            InlineKeyboardButton("🔰 Extend Premium", callback_data=f"a_extendprem_{uid}"),
            InlineKeyboardButton("❌ Revoke Premium", callback_data=f"a_revokeprem_{uid}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("🔰 Grant Premium", callback_data=f"a_extendprem_{uid}"),
        ])
    rows.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")])

    await update.message.reply_text(
        msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ConversationHandler.END


async def cb_quickban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_quickban_", ""))
    await db.ban_user(uid, True)
    await q.message.reply_text(f"🚫 User `{uid}` *banned*.", parse_mode="Markdown", reply_markup=back_kb())


async def cb_quickunban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_quickunban_", ""))
    await db.ban_user(uid, False)
    await q.message.reply_text(f"✅ User `{uid}` *unbanned*.", parse_mode="Markdown", reply_markup=back_kb())


async def cb_giftuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_giftuser_", ""))
    ctx.user_data["gift_target_uid"] = uid
    await q.message.reply_text(
        f"🎁 *Gift Premium to User `{uid}`*\n\n"
        "How many days to gift? (enter a number):",
        parse_mode="Markdown",
    )
    return GIFT_DAYS_INPUT


# ── Ban / Unban ───────────────────────────────────────────────────────────────
async def cb_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"🚫 *Ban User*\n\n{DIVIDER}\n"
        "Enter User ID or @username:",
        parse_mode="Markdown")
    return BAN_INPUT


async def handle_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    target = update.message.text.strip().lstrip("@")
    users = await db.get_all_users()
    found = next((u for u in users if str(u["user_id"]) == target or u.get("username") == target), None)
    if not found:
        await update.message.reply_text("❌ User not found.", reply_markup=back_kb())
        return ConversationHandler.END
    await db.ban_user(found["user_id"], True)
    await update.message.reply_text(
        f"🚫 *Banned:* @{found.get('username') or found['user_id']} (`{found['user_id']}`)",
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    try:
        await ctx.bot.send_message(chat_id=found["user_id"],
            text="🚫 *You have been banned from this bot.*\n\nContact support if you think this is a mistake.",
            parse_mode="Markdown")
    except Exception:
        pass
    return ConversationHandler.END


async def cb_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"✅ *Unban User*\n\n{DIVIDER}\n"
        "Enter User ID or @username:",
        parse_mode="Markdown")
    return UNBAN_INPUT


async def handle_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    target = update.message.text.strip().lstrip("@")
    users = await db.get_all_users()
    found = next((u for u in users if str(u["user_id"]) == target or u.get("username") == target), None)
    if not found:
        await update.message.reply_text("❌ User not found.", reply_markup=back_kb())
        return ConversationHandler.END
    await db.ban_user(found["user_id"], False)
    await update.message.reply_text(
        f"✅ *Unbanned:* @{found.get('username') or found['user_id']}",
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    try:
        await ctx.bot.send_message(chat_id=found["user_id"],
            text="✅ *Your ban has been lifted.* You can use the bot again.",
            parse_mode="Markdown")
    except Exception:
        pass
    return ConversationHandler.END


# ── Gift Codes ────────────────────────────────────────────────────────────────
async def cb_gift(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    ctx.user_data.pop("gift_target_uid", None)
    ctx.user_data.pop("gift_code_text", None)
    ctx.user_data.pop("gift_days", None)
    await q.message.reply_text(
        f"🎁 *Create Gift Code*\n\n"
        f"{DIVIDER}\n"
        f"*Step 1 of 3 — Type your custom code:*\n\n"
        "Letters and numbers only, no spaces.\n"
        "Examples: `WELCOME2024`, `VIP50OFF`, `PROMO99`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return GIFT_CODE_INPUT


async def handle_gift_code_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    code = update.message.text.strip().upper().replace(" ", "")
    if not code.isalnum() or len(code) < 3:
        await update.message.reply_text(
            "⚠️ Code must be at least 3 characters and contain only letters/numbers. Try again:"
        )
        return GIFT_CODE_INPUT
    ctx.user_data["gift_code_text"] = code
    await update.message.reply_text(
        f"✅ Code set: `{code}`\n\n"
        f"*Step 2 of 3 — How many days should this Premium code be valid for?*\n\n"
        "Enter any number — examples:\n"
        "`1` = 1 Day   ·   `7` = 7 Days   ·   `30` = 30 Days   ·   `999` = Unlimited",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return GIFT_DAYS_INPUT


async def handle_gift_days_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return ConversationHandler.END
    days = int(q.data.replace("giftday_", ""))
    ctx.user_data["gift_days"] = days
    label = "Unlimited (Lifetime)" if days >= 999 else f"{days} day(s)"
    await q.message.reply_text(
        f"✅ Duration set: *{label}*\n\n"
        f"*Step 3 of 3 — How many users can use this code?*\n\n"
        "Enter a number:\n"
        "`1` = single use   `10` = 10 users   `999` = unlimited",
        parse_mode="Markdown",
    )
    return GIFT_MAXUSES_INPUT


async def handle_gift_maxuses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    try:
        max_uses = int(update.message.text.strip())
        if max_uses < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid number (minimum 1):")
        return GIFT_MAXUSES_INPUT

    code = ctx.user_data.pop("gift_code_text", None)
    days = ctx.user_data.pop("gift_days", None)
    if not code or days is None:
        await update.message.reply_text(
            "⚠️ Something went wrong. Please start over.",
            reply_markup=admin_menu_kb()
        )
        return ConversationHandler.END

    await db.create_gift_code(code, days, max_uses)
    label = "Unlimited (Lifetime)" if days >= 999 else f"{days} day(s)"
    uses_label = "Unlimited uses" if max_uses >= 999 else f"{max_uses} user(s)"
    await update.message.reply_text(
        f"✅ *Gift Code Created!*\n\n"
        f"{DIVIDER}\n"
        f"🎁 Code: `{code}`\n"
        f"⏳ Duration: *{label}*\n"
        f"👥 Max Uses: *{uses_label}*\n"
        f"{DIVIDER}\n\n"
        "Share this code with your users.\n"
        "They redeem it via 🎁 Redeem Code button.",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


async def handle_gift_days_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handles GIFT_DAYS_INPUT text for two flows:
      • Code creation  — gift_code_text is present in user_data
      • Direct gifting — gift_target_uid is present in user_data
    """
    if not await admin_only(update):
        return ConversationHandler.END
    try:
        days = int(update.message.text.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid number (minimum 1). Try again:")
        return GIFT_DAYS_INPUT

    label = "Unlimited (Lifetime)" if days >= 999 else f"{days} day(s)"

    # ── Code creation flow ────────────────────────────────────────────────────
    if ctx.user_data.get("gift_code_text"):
        ctx.user_data["gift_days"] = days
        await update.message.reply_text(
            f"✅ Duration set: *{label}*\n\n"
            f"{DIVIDER}\n"
            f"*Step 3 of 3 — How many users can redeem this code?*\n\n"
            "Enter a number:\n"
            "`1` = only one user   ·   `2` = two users   ·   `999` = unlimited",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
            ),
        )
        return GIFT_MAXUSES_INPUT

    # ── Direct user gifting flow (Search User → Gift Premium) ─────────────────
    target_uid = ctx.user_data.pop("gift_target_uid", None)
    if not target_uid:
        await update.message.reply_text("⚠️ No target user. Please start over.", reply_markup=admin_menu_kb())
        return ConversationHandler.END

    await db.set_premium(target_uid, f"gift_{days}d", days)
    await db.increment_plans(target_uid)
    try:
        await ctx.bot.send_message(
            chat_id=target_uid,
            text=(
                f"🎁 *You've received a Premium Gift!*\n\n"
                f"👑 Premium activated for *{label}*\n"
                "Enjoy unlimited DMs! 🚀"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ *{label} premium gifted to user `{target_uid}`!*",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


# ── Revenue Stats ─────────────────────────────────────────────────────────────
async def cb_revenue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    payments = await db.get_all_payments()
    approved = [p for p in payments if p["status"] == "approved"]
    pending = [p for p in payments if p["status"] == "pending"]
    rejected = [p for p in payments if p["status"] == "rejected"]

    total_rev = sum(p["amount"] for p in approved)

    # Per-plan breakdown
    plan_counts: dict = {}
    for p in approved:
        pk = p["plan_key"]
        plan_counts[pk] = plan_counts.get(pk, {"count": 0, "rev": 0})
        plan_counts[pk]["count"] += 1
        plan_counts[pk]["rev"] += p["amount"]

    all_plans = await db.get_plans()
    plan_lines = ""
    for pk, data in sorted(plan_counts.items(), key=lambda x: -x[1]["rev"]):
        plan = all_plans.get(pk, {})
        plan_lines += f"  {plan.get('label', pk)}: *{data['count']}x* = ₹{data['rev']}\n"

    msg = (
        f"📊 *REVENUE ANALYTICS*\n"
        f"{DIVIDER}\n"
        f"💵 Total Revenue: *₹{total_rev:,}*\n"
        f"✅ Approved: *{len(approved)}*\n"
        f"⏳ Pending: *{len(pending)}*\n"
        f"❌ Rejected: *{len(rejected)}*\n\n"
        f"📦 *BREAKDOWN BY PLAN*\n"
        f"{DIVIDER}\n"
        f"{plan_lines or '  No approved payments yet.'}"
    )
    await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=back_kb())


# ── Pending Payments ──────────────────────────────────────────────────────────
async def cb_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    payments = await db.get_pending_payments()
    if not payments:
        await q.message.reply_text(
            f"✅ *No Pending Payments*\n\n{DIVIDER}\nAll clear!", parse_mode="Markdown", reply_markup=back_kb())
        return
    all_plans = await db.get_plans()
    for p in payments:
        plan = all_plans.get(p["plan_key"], {})
        order_line = f"🪪 Order: `{p['order_id']}`\n" if p.get("order_id") else ""
        msg = (
            f"⏳ *PAYMENT #{p['id']}*\n"
            f"{DIVIDER}\n"
            f"👤 @{p.get('username') or 'N/A'} | `{p['user_id']}`\n"
            f"📦 Plan: *{plan.get('label', p['plan_key'])}* — ₹{p['amount']}\n"
            f"{order_line}"
            f"🔖 UTR: `{p.get('utr') or 'N/A'}`\n"
            f"📅 Date: `{str(p['created_at'])[:16]}`"
        )
        await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=payment_action_kb(p["id"]))


async def cb_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Approving…")
    if not await admin_only(update):
        return
    payment_id = int(q.data.replace("pay_approve_", ""))
    payment = await db.get_payment(payment_id)
    if not payment:
        await q.message.reply_text("Payment not found.")
        return
    all_plans = await db.get_plans()
    plan = all_plans.get(payment["plan_key"], {})
    days = plan.get("days", 1)
    await db.set_premium(payment["user_id"], payment["plan_key"], days)
    await db.update_payment(payment_id, status="approved", reviewed_at="CURRENT_TIMESTAMP")
    await db.increment_plans(payment["user_id"])
    order_id = payment.get("order_id") or ""
    now_str = datetime.now().strftime("%d %b %Y, %H:%M")
    await q.message.edit_reply_markup(reply_markup=None)
    await q.message.reply_text(
        f"✅ *Payment #{payment_id} Approved!*\n\n"
        f"User `{payment['user_id']}` → *{plan.get('label')}* ({days}d)"
        + (f"\n🪪 Order: `{order_id}`" if order_id else ""),
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    try:
        order_line = f"🪪 Order ID: `{order_id}`\n" if order_id else ""
        utr_line = f"🔖 UTR: `{payment.get('utr') or 'N/A'}`\n" if payment.get("utr") else ""
        await ctx.bot.send_message(
            chat_id=payment["user_id"],
            text=(
                f"🎉 *Payment Approved — Premium Active!*\n\n"
                f"{DIVIDER}\n"
                f"{order_line}"
                f"📦 Plan: *{plan.get('label', payment['plan_key'])}*\n"
                f"⏳ Duration: *{days} day(s)*\n"
                f"💰 Amount: ₹{payment['amount']}\n"
                f"{utr_line}"
                f"📅 Approved: {now_str}\n"
                f"{DIVIDER}\n\n"
                "🚀 You now have *unlimited* DM sending. Let's go!"
            ),
            parse_mode="Markdown",
        )
    except Exception as ex:
        logger.warning(f"Could not notify user {payment['user_id']}: {ex}")


async def cb_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Rejecting…")
    if not await admin_only(update):
        return
    payment_id = int(q.data.replace("pay_reject_", ""))
    payment = await db.get_payment(payment_id)
    if not payment:
        await q.message.reply_text("Payment not found.")
        return
    await db.update_payment(payment_id, status="rejected", reviewed_at="CURRENT_TIMESTAMP")
    await q.message.edit_reply_markup(reply_markup=None)
    await q.message.reply_text(
        f"❌ *Payment #{payment_id} Rejected.*",
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    support = await db.get_setting("support_username", ADMIN_USERNAME)
    try:
        await ctx.bot.send_message(
            chat_id=payment["user_id"],
            text=(
                f"❌ *Your payment was rejected.*\n\n"
                f"{DIVIDER}\n"
                "This may be due to an invalid UTR or payment not received.\n\n"
                f"Please contact support: @{support}"
            ),
            parse_mode="Markdown",
        )
    except Exception as ex:
        logger.warning(f"Could not notify user {payment['user_id']}: {ex}")


# ── All Payments ──────────────────────────────────────────────────────────────
async def cb_allpayments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    payments = await db.get_all_payments()
    if not payments:
        await q.message.reply_text("No payments yet.", reply_markup=back_kb())
        return
    all_plans = await db.get_plans()
    chunks = []
    chunk = f"💰 *ALL PAYMENTS ({len(payments)} total)*\n{DIVIDER}\n"
    for p in payments:
        plan = all_plans.get(p["plan_key"], {})
        icon = {"approved": "✅", "rejected": "❌", "pending": "⏳"}.get(p["status"], "❓")
        order_part = f" | 🪪`{p['order_id']}`" if p.get("order_id") else ""
        line = (
            f"{icon} `{p['user_id']}` @{p.get('username') or 'N/A'} | "
            f"{plan.get('label', p['plan_key'])} ₹{p['amount']}{order_part} | "
            f"UTR:`{p.get('utr') or 'N/A'}` | {str(p['created_at'])[:10]}\n"
        )
        if len(chunk) + len(line) > 3800:
            chunks.append(chunk)
            chunk = ""
        chunk += line
    if chunk:
        chunks.append(chunk)
    for c in chunks:
        await q.message.reply_text(c, parse_mode="Markdown", reply_markup=back_kb())


# ── Broadcast ─────────────────────────────────────────────────────────────────
def _msg_type_label(msg) -> str:
    """Return a human-readable label for the message type."""
    if msg.text:
        return "✍️ Text Message"
    if msg.photo:
        return "🖼️ Photo" + (" + Caption" if msg.caption else "")
    if msg.video:
        return "🎬 Video" + (" + Caption" if msg.caption else "")
    if msg.animation:
        return "🎞️ GIF / Animation" + (" + Caption" if msg.caption else "")
    if msg.document:
        return "📎 Document / File" + (" + Caption" if msg.caption else "")
    if msg.audio:
        return "🎵 Audio" + (" + Caption" if msg.caption else "")
    if msg.voice:
        return "🎙️ Voice Message"
    if msg.video_note:
        return "📹 Video Note (Round)"
    if msg.sticker:
        return "🎭 Sticker"
    if msg.poll:
        return "📊 Poll"
    if msg.contact:
        return "👤 Contact"
    if msg.location:
        return "📍 Location"
    if msg.venue:
        return "🏢 Venue"
    return "📨 Message"


async def cb_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show broadcast audience selector with live counts."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    users = await db.get_all_users()
    active = [u for u in users if not u.get("is_banned")]
    premium = await db.get_all_premium_users()
    prem_ids = {p["user_id"] for p in premium}
    free_count = sum(1 for u in active if u["user_id"] not in prem_ids)

    await q.message.reply_text(
        f"📢 *BROADCAST*\n"
        f"{DIVIDER}\n"
        f"Send any message — text, photo, video, GIF, animation, document,\n"
        f"audio, voice, sticker, poll, and premium emoji are all supported.\n"
        f"The message will be delivered *exactly as you send it* to every recipient.\n\n"
        f"👥 *Choose your target audience:*\n\n"
        f"  📢 All active users:   *{len(active)}*\n"
        f"  👑 Premium only:       *{len(prem_ids)}*\n"
        f"  🆓 Free plan only:     *{free_count}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📢 All Users  ({len(active)})", callback_data="a_bc_all")],
            [InlineKeyboardButton(f"👑 Premium Only  ({len(prem_ids)})", callback_data="a_bc_premium")],
            [InlineKeyboardButton(f"🆓 Free Only  ({free_count})", callback_data="a_bc_free")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="a_back")],
        ]),
    )


async def _enter_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bc_filter: str):
    """Shared entry point — stores filter, asks admin to send their message."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return ConversationHandler.END

    labels = {
        "all": "📢 All Users",
        "premium": "👑 Premium Users Only",
        "free": "🆓 Free Users Only",
    }
    ctx.user_data["bc_filter"] = bc_filter

    await q.message.reply_text(
        f"📢 *BROADCAST  →  {labels[bc_filter]}*\n"
        f"{DIVIDER}\n\n"
        f"✅ *Supported message types:*\n"
        f"  • Text (bold, italic, code, links, spoilers)\n"
        f"  • Photos with or without captions\n"
        f"  • Videos with or without captions\n"
        f"  • GIFs & Animations\n"
        f"  • Documents & Files\n"
        f"  • Audio & Voice messages\n"
        f"  • Video notes (round videos)\n"
        f"  • Stickers (including animated & premium)\n"
        f"  • Polls\n"
        f"  • Premium emoji\n\n"
        f"📨 *Send your broadcast message now.*\n"
        f"The bot will show you a preview and ask for confirmation before sending.\n\n"
        f"_Tip: You can forward a message from any chat here — it will be copied exactly._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]
        ]),
    )
    return BROADCAST_INPUT


async def cb_broadcast_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _enter_broadcast(update, ctx, "all")


async def cb_broadcast_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _enter_broadcast(update, ctx, "premium")


async def cb_broadcast_free(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _enter_broadcast(update, ctx, "free")


async def handle_broadcast_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Step 1 of 2 — admin sends their message.
    Store its origin and show a preview confirmation before broadcasting.
    """
    if not await admin_only(update):
        return ConversationHandler.END

    msg = update.message
    bc_filter = ctx.user_data.get("bc_filter", "all")

    # Persist enough info to copy the message later
    ctx.user_data["bc_from_chat"] = msg.chat_id
    ctx.user_data["bc_msg_id"] = msg.message_id

    # Count targets
    users = await db.get_all_users()
    active = [u for u in users if not u.get("is_banned")]
    premium = await db.get_all_premium_users()
    prem_ids = {p["user_id"] for p in premium}

    if bc_filter == "premium":
        targets = [u for u in active if u["user_id"] in prem_ids]
    elif bc_filter == "free":
        targets = [u for u in active if u["user_id"] not in prem_ids]
    else:
        targets = active

    ctx.user_data["bc_targets"] = [u["user_id"] for u in targets]

    filter_labels = {
        "all": "📢 All Users",
        "premium": "👑 Premium Only",
        "free": "🆓 Free Only",
    }
    type_label = _msg_type_label(msg)

    # Forward / copy the message back so admin can visually verify it
    try:
        await ctx.bot.copy_message(
            chat_id=msg.chat_id,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
    except Exception:
        pass  # If copy fails (e.g. poll) just skip the preview echo

    await msg.reply_text(
        f"👆 *Message preview above*\n\n"
        f"{DIVIDER}\n"
        f"📋 *Broadcast Summary*\n\n"
        f"  🗂 Type:       *{type_label}*\n"
        f"  👥 Audience:   *{filter_labels[bc_filter]}*\n"
        f"  📬 Recipients: *{len(targets):,} users*\n\n"
        f"{DIVIDER}\n"
        f"This message will be delivered *exactly as shown* above —\n"
        f"all formatting, media, emoji, captions, and styles are preserved.\n\n"
        f"⚠️ *This action cannot be undone.* Ready to broadcast?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Yes — Send Broadcast Now", callback_data="bc_confirm_send")],
            [InlineKeyboardButton("❌ Cancel — Don't Send", callback_data="bc_confirm_cancel")],
        ]),
    )
    return BROADCAST_CONFIRM


async def cb_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Step 2 of 2 — admin confirmed. Run the broadcast using copy_message so
    every message type (including premium emoji, stickers, polls, etc.) is
    delivered pixel-perfect to all recipients.
    """
    q = update.callback_query
    await q.answer("🚀 Starting broadcast…")
    if not await admin_only(update):
        return ConversationHandler.END

    from_chat = ctx.user_data.pop("bc_from_chat", None)
    msg_id = ctx.user_data.pop("bc_msg_id", None)
    target_ids = ctx.user_data.pop("bc_targets", [])
    ctx.user_data.pop("bc_filter", None)

    if not from_chat or not msg_id or not target_ids:
        await q.message.reply_text(
            "⚠️ *Session expired.* Please start the broadcast again.",
            parse_mode="Markdown",
            reply_markup=admin_menu_kb(),
        )
        return ConversationHandler.END

    total = len(target_ids)
    sent = 0
    blocked = 0
    failed = 0

    # Live progress message
    status_msg = await q.message.reply_text(
        f"📢 *Broadcast in progress…*\n\n"
        f"{DIVIDER}\n"
        f"`[{'░' * 20}]`  0 %\n"
        f"📬 Sent: *0* / *{total:,}*\n"
        f"🚫 Blocked: *0*  |  ❌ Failed: *0*",
        parse_mode="Markdown",
    )

    # Semaphore keeps us within Telegram's ~30 msg/s guideline
    sem = asyncio.Semaphore(20)

    async def _send(uid: int):
        nonlocal sent, blocked, failed
        async with sem:
            try:
                await ctx.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat,
                    message_id=msg_id,
                )
                sent += 1
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in (
                    "blocked", "chat not found", "deactivated",
                    "user is deactivated", "bot was blocked", "forbidden",
                )):
                    blocked += 1
                else:
                    failed += 1

    batch = 50
    last_pct = -1
    for i in range(0, total, batch):
        chunk = target_ids[i: i + batch]
        await asyncio.gather(*[_send(uid) for uid in chunk])

        done = min(i + batch, total)
        pct = round(100 * done / total) if total else 100
        if pct != last_pct:
            last_pct = pct
            filled = round(20 * done / total) if total else 20
            bar = "█" * filled + "░" * (20 - filled)
            try:
                await status_msg.edit_text(
                    f"📢 *Broadcast in progress…*\n\n"
                    f"{DIVIDER}\n"
                    f"`[{bar}]`  {pct} %\n"
                    f"📬 Sent: *{sent:,}* / *{total:,}*\n"
                    f"🚫 Blocked: *{blocked:,}*  |  ❌ Failed: *{failed:,}*",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        if i + batch < total:
            await asyncio.sleep(0.5)  # brief pause between batches

    # ── Final report ──────────────────────────────────────────────────────────
    delivery_rate = round(100 * sent / total) if total else 0
    await status_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"{DIVIDER}\n"
        f"📬 Delivered:     *{sent:,}*  ({delivery_rate}%)\n"
        f"🚫 Blocked/Left:  *{blocked:,}*\n"
        f"❌ Other Errors:  *{failed:,}*\n"
        f"👥 Total Targets: *{total:,}*\n"
        f"{DIVIDER}\n\n"
        f"{'🎉 All messages delivered!' if failed == 0 and blocked == 0 else '⚠️ Some users could not be reached (they may have blocked the bot or deactivated their account).'}",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


async def cb_broadcast_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin cancelled the broadcast at the confirmation step."""
    q = update.callback_query
    await q.answer("Cancelled.")
    if not await admin_only(update):
        return ConversationHandler.END

    ctx.user_data.pop("bc_from_chat", None)
    ctx.user_data.pop("bc_msg_id", None)
    ctx.user_data.pop("bc_targets", None)
    ctx.user_data.pop("bc_filter", None)

    await q.message.reply_text(
        "❌ *Broadcast cancelled.* No messages were sent.",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


# ── Maintenance Mode toggle ────────────────────────────────────────────────────
async def cb_maintenance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    is_on = await db.get_maintenance_mode()
    status_icon = "🔴 ON" if is_on else "🟢 OFF"
    await q.message.reply_text(
        f"🔧 *MAINTENANCE MODE*\n\n"
        f"{DIVIDER}\n"
        f"Current Status: *{status_icon}*\n\n"
        f"When ON, regular users will see a maintenance message\n"
        f"and cannot use the bot until it is turned OFF.\n"
        f"{DIVIDER}\n\n"
        "Select an action 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Turn ON (block users)", callback_data="a_maintenance_on")],
            [InlineKeyboardButton("🟢 Turn OFF (allow users)", callback_data="a_maintenance_off")],
            [InlineKeyboardButton("🔙 Back", callback_data="a_back")],
        ]),
    )


async def cb_maintenance_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await db.set_maintenance_mode(True)
    await q.message.edit_text(
        f"🔴 *Maintenance Mode: ON*\n\n"
        f"{DIVIDER}\n"
        "Users are now blocked from using the bot.\n"
        "They will see a maintenance message.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 Turn OFF", callback_data="a_maintenance_off")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


async def cb_maintenance_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await db.set_maintenance_mode(False)
    await q.message.edit_text(
        f"🟢 *Maintenance Mode: OFF*\n\n"
        f"{DIVIDER}\n"
        "Bot is now live. Users can access it normally.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Turn ON", callback_data="a_maintenance_on")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


# ── UPI Payment Settings (dedicated top-level screen) ─────────────────────────
async def cb_upi_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    upi = await db.get_setting("upi_id", UPI_ID)
    # Generate a live test QR for the admin to preview
    qr_bytes = None
    try:
        import qr_utils
        from io import BytesIO
        qr_bytes = BytesIO(qr_utils.generate_upi_qr(upi, 1, "TEST-PREVIEW"))
    except Exception:
        pass

    text = (
        f"💳 *UPI PAYMENT SETTINGS*\n\n"
        f"{DIVIDER}\n"
        f"📲 Current UPI ID:\n`{upi}`\n"
        f"{DIVIDER}\n\n"
        "The QR code below is a live preview for ₹1.\n"
        "Each user gets a *unique per-order QR* generated automatically.\n\n"
        "Tap *Change UPI ID* to update.",
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set UPI ID", callback_data="a_set_upi")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])
    if qr_bytes:
        try:
            await q.message.reply_photo(
                photo=qr_bytes,
                caption=(
                    f"💳 *UPI PAYMENT SETTINGS*\n\n"
                    f"{DIVIDER}\n"
                    f"📲 Current UPI ID:\n`{upi}`\n"
                    f"{DIVIDER}\n\n"
                    "This is a live test QR (₹1). Each user gets a unique\n"
                    "per-order QR generated automatically.\n\n"
                    "Tap *Change UPI ID* to update."
                ),
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return
        except Exception:
            pass
    await q.message.reply_text(
        f"💳 *UPI PAYMENT SETTINGS*\n\n"
        f"{DIVIDER}\n"
        f"📲 Current UPI ID:\n`{upi}`\n"
        f"{DIVIDER}\n\n"
        "Each user gets a unique per-order QR generated automatically.\n"
        "Tap *Change UPI ID* to update.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ── Linked Users (accounts) ───────────────────────────────────────────────────
async def cb_linked_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    accounts = await db.get_linked_accounts_list()
    if not accounts:
        await q.message.reply_text(
            f"📱 *LINKED ACCOUNTS*\n\n"
            f"{DIVIDER}\n"
            "No accounts linked yet.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return
    lines = []
    for acc in accounts[:50]:
        uname = f"@{acc['username']}" if acc.get("username") else "—"
        added = str(acc.get("added_at", ""))[:10]
        lines.append(f"• `{acc['user_id']}` {uname} | 📱 `{acc['phone']}` | {added}")
    text = (
        f"📱 *LINKED ACCOUNTS ({len(accounts)} total)*\n\n"
        f"{DIVIDER}\n"
        + "\n".join(lines)
    )
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())


# ── Image Upload: Welcome & QR ─────────────────────────────────────────────────
async def cb_upload_welcome_img(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"🖼 *Change Welcome Image*\n\n"
        f"{DIVIDER}\n"
        "Send a *photo* to use as the new welcome image.\n"
        "It will replace the current welcome image for all users.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return UPLOAD_WELCOME_IMG


async def handle_upload_welcome_img(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a photo.", reply_markup=edit_menu_kb())
        return UPLOAD_WELCOME_IMG
    import os
    os.makedirs("data", exist_ok=True)
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    path = os.path.join("data", "welcome_custom.jpg")
    await file.download_to_drive(path)
    await update.message.reply_text(
        "✅ *Welcome image updated!*\n\nNew image will appear for all users on /start.",
        parse_mode="Markdown",
        reply_markup=edit_menu_kb(),
    )
    return ConversationHandler.END


async def cb_upload_qr_img(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"📷 *Change QR / Payment Image*\n\n"
        f"{DIVIDER}\n"
        "Send a *photo* to use as the new payment QR image.\n"
        "It will appear on the payment screen when users upgrade.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_edit")]]),
    )
    return UPLOAD_QR_IMG


async def handle_upload_qr_img(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a photo.", reply_markup=edit_menu_kb())
        return UPLOAD_QR_IMG
    import os
    os.makedirs("data", exist_ok=True)
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    path = os.path.join("data", "qr_custom.jpg")
    await file.download_to_drive(path)
    await update.message.reply_text(
        "✅ *QR image updated!*\n\nNew QR will appear on the payment screen.",
        parse_mode="Markdown",
        reply_markup=edit_menu_kb(),
    )
    return ConversationHandler.END


async def cb_promo_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    orders = await db.get_pending_promo_orders()
    if not orders:
        await q.message.reply_text(
            f"✅ *No Pending Promo Orders*\n\n{DIVIDER}\nAll clear!",
            parse_mode="Markdown", reply_markup=back_kb())
        return
    for o in orders:
        uname = f"@{o['username']}" if o.get("username") else "N/A"
        msg = (
            f"📣 *PROMO ORDER*\n"
            f"{DIVIDER}\n"
            f"🪪 Order ID: `{o['order_id']}`\n"
            f"👤 {uname} | `{o['user_id']}`\n"
            f"🔗 Channel: `{o['channel_link']}`\n"
            f"👥 Members: *{o['member_count']:,}*\n"
            f"💰 Price/Member: ₹{o['price_per_member']:g}\n"
            f"💵 Total: *₹{o['total_price']:g}*\n"
            f"🔖 UTR: `{o.get('utr') or 'N/A'}`\n"
            f"📅 Date: `{str(o['created_at'])[:16]}`"
        )
        await q.message.reply_text(
            msg, parse_mode="Markdown",
            reply_markup=promo_order_action_kb(o["order_id"]),
        )


async def cb_promo_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Approving…")
    if not await admin_only(update):
        return
    order_id = q.data.replace("promo_approve_", "")
    order = await db.get_promo_order_by_id(order_id)
    if not order:
        await q.message.reply_text("Order not found.")
        return
    await db.update_promo_order(order_id, status="approved", reviewed_at="CURRENT_TIMESTAMP")
    await q.message.edit_reply_markup(reply_markup=None)
    await q.message.reply_text(
        f"✅ *Promo Order Approved!*\n\n"
        f"🪪 Order: `{order_id}`\n"
        f"🔗 Channel: `{order['channel_link']}`\n"
        f"👥 Members: *{order['member_count']:,}*",
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    try:
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await ctx.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"✅ *Your Channel Promo Order is Approved!*\n\n"
                f"{DIVIDER}\n"
                f"🪪 Order ID: `{order_id}`\n"
                f"🔗 Channel: `{order['channel_link']}`\n"
                f"👥 Members Ordered: *{order['member_count']:,}*\n"
                f"💵 Amount: ₹{order['total_price']:g}\n"
                f"{DIVIDER}\n\n"
                "🚀 Your order is being processed! Members will be delivered "
                "as soon as possible.\n\n"
                f"💬 Support: @{support}"
            ),
            parse_mode="Markdown",
        )
    except Exception as ex:
        logger.warning(f"Could not notify user {order['user_id']}: {ex}")


async def cb_promo_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Rejecting…")
    if not await admin_only(update):
        return
    order_id = q.data.replace("promo_reject_", "")
    order = await db.get_promo_order_by_id(order_id)
    if not order:
        await q.message.reply_text("Order not found.")
        return
    await db.update_promo_order(order_id, status="rejected", reviewed_at="CURRENT_TIMESTAMP")
    await q.message.edit_reply_markup(reply_markup=None)
    await q.message.reply_text(
        f"❌ *Promo Order Rejected.*\n\n🪪 Order: `{order_id}`",
        parse_mode="Markdown", reply_markup=admin_menu_kb())
    try:
        support = await db.get_setting("support_username", ADMIN_USERNAME)
        await ctx.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"❌ *Your Channel Promo Order Was Rejected*\n\n"
                f"{DIVIDER}\n"
                f"🪪 Order ID: `{order_id}`\n\n"
                "This may be due to an invalid payment or UTR. "
                "Please try again or contact support.\n\n"
                f"💬 Support: @{support}"
            ),
            parse_mode="Markdown",
        )
    except Exception as ex:
        logger.warning(f"Could not notify user {order['user_id']}: {ex}")


async def cb_set_promo_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_promo_price_per_member()
    await q.message.reply_text(
        f"💸 *Set Promo Price Per Member*\n\n"
        f"{DIVIDER}\n"
        f"Current price: *₹{current:g}* per member\n\n"
        "Send the new price per member (decimals allowed, e.g. `0.05`, `0.5`, `1`):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]),
    )
    return PROMO_PRICE_INPUT


async def handle_set_promo_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        price = float(text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid price. Please send a positive number (e.g. `0.05`, `1.5`).",
            parse_mode="Markdown",
        )
        return PROMO_PRICE_INPUT
    await db.set_promo_price_per_member(price)
    await update.message.reply_text(
        f"✅ *Promo price updated!*\n\n"
        f"New price: *₹{price:g}* per member",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Cancelled.", reply_markup=admin_menu_kb())
    return ConversationHandler.END


# ── /stats command ────────────────────────────────────────────────────────────
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    dash = await _build_dashboard()
    await update.message.reply_text(dash, parse_mode="Markdown", reply_markup=admin_menu_kb())


# ── App setup ─────────────────────────────────────────────────────────────────
# ── Custom Buttons (user bot menu) ────────────────────────────────────────────
async def cb_custom_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    buttons = await db.get_custom_buttons()
    lines = "\n".join(f"  {i+1}. *{b['label']}* → `{b['url']}`" for i, b in enumerate(buttons)) or "  _None added yet._"
    await q.message.reply_text(
        f"🔗 *CUSTOM BUTTONS*\n"
        f"{DIVIDER}\n"
        f"These buttons appear in the user bot's main menu.\n\n"
        f"{lines}\n\n"
        "Choose an action 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Button", callback_data="acb_add")],
            [InlineKeyboardButton("➖ Remove Button", callback_data="acb_remove")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
        ]),
    )


async def cb_custom_btn_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"➕ *Add Custom Button*\n\n"
        f"{DIVIDER}\n"
        f"*Step 1 of 2 — Button Label*\n\n"
        "Type the text that will appear on the button.\n"
        "Examples: `📺 YouTube`, `💬 Join Channel`, `🤖 Our Bot`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_custom_buttons")]]
        ),
    )
    return CUSTOM_BTN_LABEL_INPUT


async def handle_custom_btn_label(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    label = update.message.text.strip()
    if not label:
        await update.message.reply_text("⚠️ Label cannot be empty. Try again:")
        return CUSTOM_BTN_LABEL_INPUT
    ctx.user_data["custom_btn_label"] = label
    await update.message.reply_text(
        f"✅ Label set: *{label}*\n\n"
        f"*Step 2 of 2 — Button Link*\n\n"
        "Paste anything — it all works:\n\n"
        "• `@username` or `username` → Telegram user/channel/bot\n"
        "• `https://t.me/username` → Telegram link\n"
        "• `https://t.me/+invitecode` → Private group invite\n"
        "• `https://t.me/channel/123` → Specific post\n"
        "• `https://youtube.com/...` → YouTube video\n"
        "• `https://instagram.com/...` → Instagram post\n"
        "• Any website, app link, or URL",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_custom_buttons")]]
        ),
    )
    return CUSTOM_BTN_URL_INPUT


async def handle_custom_btn_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()

    # ── Auto-convert any input into a valid button URL ─────────────────────
    # @username or bare username → https://t.me/username
    if raw.startswith("@"):
        url = f"https://t.me/{raw[1:]}"
    elif not (raw.startswith("http://") or raw.startswith("https://") or raw.startswith("tg://")):
        # Looks like a bare username (letters/numbers/underscores only) → t.me link
        import re as _re
        if _re.fullmatch(r"[A-Za-z0-9_]{3,32}", raw):
            url = f"https://t.me/{raw}"
        else:
            # Unknown format — reject with helpful message
            await update.message.reply_text(
                "⚠️ *Couldn't recognise that link.*\n\n"
                "Use any of these formats:\n"
                "• `@username` or `username`\n"
                "• `https://t.me/username`\n"
                "• `https://t.me/+invitecode`\n"
                "• `https://t.me/channel/123` (post link)\n"
                "• Any full URL starting with `https://`\n\n"
                "Try again:",
                parse_mode="Markdown",
            )
            return CUSTOM_BTN_URL_INPUT
    else:
        url = raw

    label = ctx.user_data.pop("custom_btn_label", "Button")
    await db.add_custom_button(label, url)
    await user_bot_module.reload_custom_buttons()

    buttons = await db.get_custom_buttons()
    await update.message.reply_text(
        f"✅ *Button Added!*\n\n"
        f"{DIVIDER}\n"
        f"🔗 Label: *{label}*\n"
        f"🌐 URL: `{url}`\n\n"
        f"Total custom buttons: *{len(buttons)}*\n\n"
        "The button is now live in the user bot's main menu!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Another", callback_data="acb_add")],
            [InlineKeyboardButton("🔗 View All", callback_data="a_custom_buttons")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


async def cb_custom_btn_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    buttons = await db.get_custom_buttons()
    if not buttons:
        await q.message.reply_text(
            "No custom buttons to remove.", reply_markup=back_kb())
        return
    rows = [
        [InlineKeyboardButton(f"🗑 {b['label']}", callback_data=f"acb_del_{b['id']}")]
        for b in buttons
    ]
    rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="a_custom_buttons")])
    await q.message.reply_text(
        "➖ *Remove a Custom Button*\n\nTap to remove:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cb_custom_btn_remove_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    btn_id = int(q.data.replace("acb_del_", ""))
    await db.remove_custom_button(btn_id)
    await user_bot_module.reload_custom_buttons()
    remaining = await db.get_custom_buttons()
    await q.message.reply_text(
        f"✅ *Button removed.*\n\nRemaining custom buttons: *{len(remaining)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 View All", callback_data="a_custom_buttons")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


# ── Set Price ──────────────────────────────────────────────────────────────────
async def _show_set_price_menu(message):
    plans = await db.get_plans()
    sorted_plans = sorted(plans.items(), key=lambda x: x[1].get("days", 0))

    text = (
        f"💰 *SET PRICE*\n"
        f"{DIVIDER}\n"
        f"Tap any plan to change its price.\n\n"
        f"📦 *Current Plans:*\n"
    )
    for key, plan in sorted_plans:
        text += f"  • {plan['label']} — *₹{plan['price']}*\n"

    rows = []
    for key, plan in sorted_plans:
        rows.append([InlineKeyboardButton(
            f"✏️ {plan['label']} — ₹{plan['price']}",
            callback_data=f"sp_edit_{key}",
        )])
    rows.append([InlineKeyboardButton("➕ Add New Plan", callback_data="sp_add")])
    rows.append([InlineKeyboardButton("🗑 Remove a Plan", callback_data="sp_remove")])
    rows.append([InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")])

    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


async def cb_set_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await _show_set_price_menu(q.message)


async def cb_set_price_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point — admin taps a plan row to edit its price."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return ConversationHandler.END
    plan_key = q.data.replace("sp_edit_", "")
    plans = await db.get_plans()
    plan = plans.get(plan_key)
    if not plan:
        await q.message.reply_text("❌ Plan not found.")
        return ConversationHandler.END
    ctx.user_data["sp_plan_key"] = plan_key
    await q.message.reply_text(
        f"✏️ *Edit Price: {plan['label']}*\n\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plan['label']}*\n"
        f"⏳ Duration: *{plan['days']} day(s)*\n"
        f"💰 Current price: *₹{plan['price']}*\n\n"
        f"Enter the new price in ₹ (numbers only):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_set_price")]]
        ),
    )
    return SET_PRICE_EDIT_INPUT


async def handle_price_edit_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit() or int(raw) <= 0:
        await update.message.reply_text("⚠️ Enter a valid price (positive number only). Try again:")
        return SET_PRICE_EDIT_INPUT
    price = int(raw)
    plan_key = ctx.user_data.pop("sp_plan_key", None)
    if not plan_key:
        await update.message.reply_text("⚠️ Session expired. Please start over.", reply_markup=admin_menu_kb())
        return ConversationHandler.END
    plans = await db.get_plans()
    if plan_key not in plans:
        await update.message.reply_text("❌ Plan not found.", reply_markup=admin_menu_kb())
        return ConversationHandler.END
    old_price = plans[plan_key]["price"]
    plans[plan_key]["price"] = price
    await db.save_plans(plans)
    await user_bot_module.reload_plans()
    await update.message.reply_text(
        f"✅ *Price Updated!*\n\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{plans[plan_key]['label']}*\n"
        f"💰 ₹{old_price} → *₹{price}*\n\n"
        f"Changes are live instantly in the user bot!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Set Price", callback_data="a_set_price")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


async def cb_set_price_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point — admin wants to add a brand-new custom plan."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return ConversationHandler.END
    await q.message.reply_text(
        f"➕ *Add New Plan*\n\n"
        f"{DIVIDER}\n"
        f"Enter the number of days for this plan:\n"
        f"_(e.g. `28` for a 28-day plan, `45` for 45 days)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_set_price")]]
        ),
    )
    return SET_PRICE_NEW_DAYS_INPUT


async def handle_new_plan_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit() or int(raw) <= 0:
        await update.message.reply_text("⚠️ Enter a valid number of days (positive integer). Try again:")
        return SET_PRICE_NEW_DAYS_INPUT
    days = int(raw)
    if days == 1:
        label = "1 Day"
    elif days == 30:
        label = "1 Month"
    elif days == 60:
        label = "2 Months"
    elif days == 90:
        label = "3 Months"
    else:
        label = f"{days} Days"
    ctx.user_data["sp_new_days"] = days
    ctx.user_data["sp_new_label"] = label
    await update.message.reply_text(
        f"✅ Duration set: *{label}*\n\n"
        f"Now enter the price for this plan in ₹ (numbers only):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_set_price")]]
        ),
    )
    return SET_PRICE_NEW_PRICE_INPUT


async def handle_new_plan_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit() or int(raw) <= 0:
        await update.message.reply_text("⚠️ Enter a valid price (positive number only). Try again:")
        return SET_PRICE_NEW_PRICE_INPUT
    price = int(raw)
    days = ctx.user_data.pop("sp_new_days", None)
    label = ctx.user_data.pop("sp_new_label", None)
    if not days or not label:
        await update.message.reply_text("⚠️ Session expired. Please start over.", reply_markup=admin_menu_kb())
        return ConversationHandler.END

    plan_key = f"{days}d"
    plans = await db.get_plans()

    if plan_key in plans:
        old_price = plans[plan_key]["price"]
        plans[plan_key]["price"] = price
        await db.save_plans(plans)
        await user_bot_module.reload_plans()
        await update.message.reply_text(
            f"ℹ️ *Plan already exists — Price Updated!*\n\n"
            f"{DIVIDER}\n"
            f"📦 Plan: *{plans[plan_key]['label']}*\n"
            f"💰 ₹{old_price} → *₹{price}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Set Price", callback_data="a_set_price")],
                [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
            ]),
        )
        return ConversationHandler.END

    plans[plan_key] = {"label": label, "days": days, "price": price}
    await db.save_plans(plans)
    await user_bot_module.reload_plans()
    await update.message.reply_text(
        f"✅ *New Plan Added!*\n\n"
        f"{DIVIDER}\n"
        f"📦 Plan: *{label}*\n"
        f"⏳ Duration: *{days} day(s)*\n"
        f"💰 Price: *₹{price}*\n\n"
        f"The plan is now live in the user bot! 🚀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Another Plan", callback_data="sp_add")],
            [InlineKeyboardButton("💰 Set Price", callback_data="a_set_price")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


async def cb_set_price_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    plans = await db.get_plans()
    sorted_plans = sorted(plans.items(), key=lambda x: x[1].get("days", 0))
    if len(plans) <= 1:
        await q.message.reply_text(
            "⚠️ You must keep at least 1 plan.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="a_set_price")]]
            ),
        )
        return
    rows = []
    for key, plan in sorted_plans:
        rows.append([InlineKeyboardButton(
            f"🗑 {plan['label']} — ₹{plan['price']}",
            callback_data=f"sp_del_{key}",
        )])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="a_set_price")])
    await q.message.reply_text(
        f"🗑 *Remove Plan*\n\n"
        f"{DIVIDER}\n"
        f"Tap a plan to permanently remove it.\n"
        f"_(At least 1 plan must remain.)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cb_set_price_remove_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    plan_key = q.data.replace("sp_del_", "")
    plans = await db.get_plans()
    if len(plans) <= 1:
        await q.message.reply_text("⚠️ You must keep at least 1 plan.")
        return
    plan = plans.pop(plan_key, None)
    if not plan:
        await q.message.reply_text("❌ Plan not found.")
        return
    await db.save_plans(plans)
    await user_bot_module.reload_plans()
    await q.message.reply_text(
        f"✅ *Plan Removed!*\n\n"
        f"{DIVIDER}\n"
        f"🗑 Removed: *{plan['label']}* (₹{plan['price']})\n"
        f"📦 Remaining plans: *{len(plans)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Set Price", callback_data="a_set_price")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


# ── Referral Settings ──────────────────────────────────────────────────────────
async def cb_referral_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    reward_days = await db.get_referral_reward_days()
    referrals = await db.get_all_referrals_admin()
    total     = len(referrals)
    completed = sum(1 for r in referrals if r["status"] == "completed")
    pending   = total - completed

    text = (
        f"🤝 *REFERRAL SETTINGS*\n\n"
        f"{DIVIDER}\n"
        f"📊 *Overall Stats:*\n"
        f"   Total Referrals: *{total}*\n"
        f"   ✅ Completed:    *{completed}*\n"
        f"   ⏳ Pending:      *{pending}*\n\n"
        f"{DIVIDER}\n"
        f"⚙️ *Current Reward:*\n"
        f"   🎁 *{reward_days} day(s) VIP Premium* per successful referral\n\n"
        f"A referral is complete when the referred user:\n"
        f"  1. Adds their Telegram account\n"
        f"  2. Sends at least 1 DM campaign"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✏️ Set Reward Days (now: {reward_days}d)", callback_data="a_ref_set_reward")],
        [InlineKeyboardButton("📋 View All Referrals", callback_data="a_referral_stats")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_referral_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    referrals = await db.get_all_referrals_admin()
    if not referrals:
        await q.message.reply_text(
            "📋 *Referrals*\n\nNo referrals yet.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="a_referral")]]),
        )
        return

    lines = [f"📋 *ALL REFERRALS* ({len(referrals)} total)\n{DIVIDER}\n"]
    for r in referrals[:30]:
        ref_name = f"@{r['referrer_username']}" if r.get("referrer_username") else str(r["referrer_id"])
        red_name = f"@{r['referred_username']}" if r.get("referred_username") else str(r["referred_user_id"])
        icon = "✅" if r["status"] == "completed" else "⏳"
        lines.append(f"{icon} {ref_name} → {red_name}")

    if len(referrals) > 30:
        lines.append(f"\n_... and {len(referrals) - 30} more_")

    await q.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="a_referral")]]),
    )


async def cb_referral_set_reward(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_referral_reward_days()
    await q.message.reply_text(
        f"✏️ *Set Referral Reward Days*\n\n"
        f"{DIVIDER}\n"
        f"Current reward: *{current} day(s)* per referral\n\n"
        f"Send the new number of VIP days to award per completed referral.\n"
        f"_(e.g. `1`, `3`, `7`)_\n\n"
        f"Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return REFERRAL_REWARD_INPUT


async def handle_referral_reward_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        days = int(text)
        if days < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Please send a valid positive number (e.g. `1`, `3`, `7`).",
            parse_mode="Markdown",
        )
        return REFERRAL_REWARD_INPUT

    await db.set_referral_reward_days(days)
    await update.message.reply_text(
        f"✅ *Referral Reward Updated!*\n\n"
        f"{DIVIDER}\n"
        f"🎁 Each successful referral now earns *{days} day(s) VIP Premium*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Referral Settings", callback_data="a_referral")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


# ── Analytics Panel ───────────────────────────────────────────────────────────
async def cb_analytics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    users = await db.get_all_users()
    payments = await db.get_all_payments()
    approved = [p for p in payments if p["status"] == "approved"]
    pending = [p for p in payments if p["status"] == "pending"]
    rejected = [p for p in payments if p["status"] == "rejected"]
    revenue = sum(p["amount"] for p in approved)
    premium_users = await db.get_all_premium_users()
    prem_ids = {p["user_id"] for p in premium_users}
    banned = [u for u in users if u.get("is_banned")]
    free_users = [u for u in users if u["user_id"] not in prem_ids and not u.get("is_banned")]
    accounts_count = await db.get_accounts_count()
    total_dms = await db.get_total_dms_sent()
    active_camps = await db.get_active_campaigns_count()
    new_today = await db.get_new_users_today()
    free_limit = await db.get_free_limit()

    # Revenue breakdown
    all_plans = await db.get_plans()
    plan_counts: dict = {}
    for p in approved:
        pk = p["plan_key"]
        plan_counts[pk] = plan_counts.get(pk, {"count": 0, "rev": 0})
        plan_counts[pk]["count"] += 1
        plan_counts[pk]["rev"] += p["amount"]

    plan_lines = ""
    for pk, data in sorted(plan_counts.items(), key=lambda x: -x[1]["rev"]):
        plan = all_plans.get(pk, {})
        plan_lines += f"  • {plan.get('label', pk)}: {data['count']}× → *₹{data['rev']}*\n"

    conversion_rate = 0.0
    if len(users) > 0:
        conversion_rate = (len(approved) / len(users)) * 100

    text = (
        f"📈 *ADVANCED ANALYTICS*\n"
        f"{DIVIDER}\n"
        f"👥 *Users*\n"
        f"  Total: *{len(users)}*  |  New today: *+{new_today}*\n"
        f"  Active Premium: *{len(premium_users)}*\n"
        f"  Free Users: *{len(free_users)}*\n"
        f"  Banned: *{len(banned)}*\n\n"
        f"📱 *Accounts & Campaigns*\n"
        f"{DIVIDER}\n"
        f"  Accounts Linked: *{accounts_count}*\n"
        f"  Total DMs Sent: *{total_dms:,}*\n"
        f"  Active Campaigns: *{active_camps}*\n"
        f"  Free DM Limit: *{free_limit}*\n\n"
        f"💰 *Payments & Revenue*\n"
        f"{DIVIDER}\n"
        f"  Total Revenue: *₹{revenue:,}*\n"
        f"  ✅ Approved: *{len(approved)}*\n"
        f"  ⏳ Pending: *{len(pending)}*\n"
        f"  ❌ Rejected: *{len(rejected)}*\n"
        f"  Conversion Rate: *{conversion_rate:.1f}%*\n\n"
        f"📦 *Revenue by Plan*\n"
        f"{DIVIDER}\n"
        f"{plan_lines or '  No approved payments yet.'}"
    )
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())


# ── Premium Users Panel ────────────────────────────────────────────────────────
async def cb_premium_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    premium = await db.get_all_premium_users()
    if not premium:
        await q.message.reply_text(
            f"👑 *Premium Users*\n\n{DIVIDER}\nNo active premium users right now.",
            parse_mode="Markdown", reply_markup=back_kb())
        return

    chunks = []
    chunk = f"👑 *ACTIVE PREMIUM USERS ({len(premium)} total)*\n{DIVIDER}\n"
    for p in premium:
        name = f"@{p['username']}" if p.get("username") else f"`{p['user_id']}`"
        try:
            from datetime import datetime as _dt, timezone as _tz
            exp = _dt.fromisoformat(p["expires_at"])
            diff = max(0, (exp - _dt.now(_tz.utc).replace(tzinfo=None)).days)
            exp_str = f"{p['expires_at'][:10]} ({diff}d left)"
        except Exception:
            exp_str = str(p["expires_at"])[:10]
        line = f"  👑 {name} — `{p['plan_key']}` — expires {exp_str}\n"
        if len(chunk) + len(line) > 3800:
            chunks.append(chunk)
            chunk = ""
        chunk += line
    if chunk:
        chunks.append(chunk)

    for c in chunks:
        await q.message.reply_text(c, parse_mode="Markdown", reply_markup=back_kb())


# ── Bot Settings Panel ─────────────────────────────────────────────────────────
async def cb_botsettings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    free_limit = await db.get_free_limit()
    refs_enabled = await db.get_setting("referrals_enabled", "1")
    refs_on = refs_enabled == "1"
    bot_name = await db.get_setting("bot_name", "Auto DMs Bot")
    wm_on = await db.get_watermark_enabled()
    wm_username = await db.get_watermark_username()

    wm_status = "✅ ON" if wm_on else "❌ OFF"
    wm_uname_display = f"@{wm_username}" if wm_username else "_(not set)_"

    text = (
        f"⚙️ *BOT SETTINGS*\n"
        f"{DIVIDER}\n"
        f"🆓 Free DM Limit: *{free_limit} DMs*\n"
        f"🤝 Referrals: {'✅ Enabled' if refs_on else '❌ Disabled'}\n"
        f"📛 Bot Name: *{bot_name}*\n"
        f"💧 Watermark: *{wm_status}*\n"
        f"   └ Username: {wm_uname_display}\n"
        f"{DIVIDER}\n\n"
        f"Select what to change 👇"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✏️ Change Free Limit (now: {free_limit})", callback_data="a_set_free_limit")],
        [InlineKeyboardButton(
            f"🤝 Toggle Referrals ({'ON → OFF' if refs_on else 'OFF → ON'})",
            callback_data="a_toggle_referrals")],
        [InlineKeyboardButton("📛 Set Bot Name", callback_data="a_set_bot_name")],
        [InlineKeyboardButton(
            f"💧 Watermark ({'ON → OFF' if wm_on else 'OFF → ON'})",
            callback_data="a_toggle_watermark")],
        [InlineKeyboardButton("✏️ Set Watermark Username", callback_data="a_set_watermark_username")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_set_free_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_free_limit()
    await q.message.reply_text(
        f"✏️ *Change Free DM Limit*\n\n"
        f"{DIVIDER}\n"
        f"Current limit: *{current} DMs* per user\n\n"
        f"Enter the new number of free DMs allowed per user:\n"
        f"_(e.g. `50`, `100`, `200`)_\n\n"
        f"Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_botsettings")]]
        ),
    )
    return FREE_LIMIT_INPUT


async def handle_free_limit_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit() or int(raw) < 1:
        await update.message.reply_text("⚠️ Enter a valid positive number. Try again:")
        return FREE_LIMIT_INPUT
    n = int(raw)
    old = await db.get_free_limit()
    await db.set_free_limit(n)
    await update.message.reply_text(
        f"✅ *Free DM Limit Updated!*\n\n"
        f"{DIVIDER}\n"
        f"🆓 {old} DMs → *{n} DMs* per user\n\n"
        f"Takes effect immediately for all new campaigns.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


async def cb_toggle_referrals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("referrals_enabled", "1")
    new_val = "0" if current == "1" else "1"
    await db.set_setting("referrals_enabled", new_val)
    status = "✅ Enabled" if new_val == "1" else "❌ Disabled"
    await q.message.reply_text(
        f"🤝 *Referrals {status}*\n\n"
        f"Users {'can' if new_val == '1' else 'cannot'} earn rewards for referring others.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


async def cb_set_bot_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_setting("bot_name", "Auto DMs Bot")
    await q.message.reply_text(
        f"📛 *Set Bot Name*\n\n"
        f"{DIVIDER}\n"
        f"Current name: *{current}*\n\n"
        f"Send the new display name for this bot:\n"
        f"_(shown in welcome messages, referral links, etc.)_\n\n"
        f"Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_botsettings")]]
        ),
    )
    return BOT_NAME_INPUT


async def handle_bot_name_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    name = update.message.text.strip()
    if not name or len(name) > 64:
        await update.message.reply_text("⚠️ Name must be 1–64 characters. Try again:")
        return BOT_NAME_INPUT
    await db.set_setting("bot_name", name)
    await update.message.reply_text(
        f"✅ *Bot Name Updated!*\n\nNew name: *{name}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


# ── Watermark Toggle & Username ────────────────────────────────────────────────
async def cb_toggle_watermark(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_watermark_enabled()
    new_val = not current
    await db.set_watermark_enabled(new_val)
    wm_username = await db.get_watermark_username()
    status = "✅ ON" if new_val else "❌ OFF"
    preview = f"\n\n💬 Watermark text:\n_\"This message was sent by @{wm_username}.\"_" if (new_val and wm_username) else (
        "\n\n⚠️ No username set yet — tap *Set Watermark Username* to configure." if new_val else ""
    )
    await q.message.reply_text(
        f"💧 *Watermark {status}*\n\n"
        f"{DIVIDER}\n"
        + ("Every outgoing DM will now end with the watermark.\n" if new_val else "Watermark removed from all outgoing DMs.\n")
        + preview,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Set Watermark Username", callback_data="a_set_watermark_username")],
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )


async def cb_set_watermark_username(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    current = await db.get_watermark_username()
    display = f"@{current}" if current else "_(not set)_"
    await q.message.reply_text(
        f"✏️ *Set Watermark Username*\n\n"
        f"{DIVIDER}\n"
        f"Current: {display}\n\n"
        "Enter the username to show in the watermark.\n"
        "Type with or without the `@` — both work.\n\n"
        "_Example: `ForwardDMBot` → watermark becomes:_\n"
        "_\"This message was sent by @ForwardDMBot.\"_\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_botsettings")]]
        ),
    )
    return WATERMARK_USERNAME_INPUT


async def handle_watermark_username_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    raw = update.message.text.strip().lstrip("@")
    if not raw or len(raw) > 64:
        await update.message.reply_text("⚠️ Username must be 1–64 characters. Try again:")
        return WATERMARK_USERNAME_INPUT
    await db.set_watermark_username(raw)
    wm_on = await db.get_watermark_enabled()
    status_note = "💧 Watermark is currently *ON* — the new username is live." if wm_on else "💧 Watermark is currently *OFF* — enable it in Bot Settings to activate."
    await update.message.reply_text(
        f"✅ *Watermark Username Updated!*\n\n"
        f"{DIVIDER}\n"
        f"Username: `@{raw}`\n\n"
        f"Watermark text:\n_\"This message was sent by @{raw}.\"_\n\n"
        f"{DIVIDER}\n"
        f"{status_note}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="a_botsettings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


# ── Gmail Credentials ─────────────────────────────────────────────────────────
async def cb_gmail_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    import gmail_checker as gc
    email_set = bool(gc.GMAIL_ADDRESS)
    pass_set = bool(gc.GMAIL_APP_PASSWORD)
    email_display = gc.GMAIL_ADDRESS if email_set else "_(not set)_"
    pass_display = "✅ Configured" if pass_set else "❌ Not set"

    status = "✅ Ready" if (email_set and pass_set) else "⚠️ Not configured"

    text = (
        f"📧 *GMAIL VERIFICATION SETTINGS*\n"
        f"{DIVIDER}\n"
        f"Status: *{status}*\n\n"
        f"📬 Gmail: {email_display}\n"
        f"🔑 App Password: {pass_display}\n"
        f"{DIVIDER}\n\n"
        "The bot uses Gmail to *auto-verify UPI payments*.\n"
        "When a user submits a UTR, the bot checks your inbox for a matching payment email.\n\n"
        "📌 *Setup steps:*\n"
        "1. Enable 2-Step Verification on your Gmail\n"
        "2. Go to Google Account → Security → App Passwords\n"
        "3. Generate a password for 'Mail'\n"
        "4. Enter the Gmail address and App Password below\n\n"
        "_Note: Use a Gmail that receives UPI payment receipts._"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set Gmail Address", callback_data="a_set_gmail_email")],
        [InlineKeyboardButton("🔑 Set App Password", callback_data="a_set_gmail_pass")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="a_back")],
    ])
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_set_gmail_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    import gmail_checker as gc
    current = gc.GMAIL_ADDRESS or "_(not set)_"
    await q.message.reply_text(
        f"📬 *Set Gmail Address*\n\n"
        f"{DIVIDER}\n"
        f"Current: {current}\n"
        f"{DIVIDER}\n\n"
        "Enter the Gmail address that receives your UPI payment receipts.\n\n"
        "_Example: `yourname@gmail.com`_\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_gmail_settings")]]
        ),
    )
    return GMAIL_EMAIL_INPUT


async def handle_gmail_email_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    import gmail_checker as gc
    raw = update.message.text.strip()
    if "@" not in raw or "." not in raw:
        await update.message.reply_text("⚠️ That doesn't look like a valid email. Try again:")
        return GMAIL_EMAIL_INPUT
    await db.set_setting("gmail_address", raw)
    gc.GMAIL_ADDRESS = raw
    await update.message.reply_text(
        f"✅ *Gmail Address Updated!*\n\n"
        f"📬 `{raw}`\n\n"
        "Now set your *Gmail App Password* so the bot can read emails.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Set App Password", callback_data="a_set_gmail_pass")],
            [InlineKeyboardButton("📧 Gmail Settings", callback_data="a_gmail_settings")],
        ]),
    )
    return ConversationHandler.END


async def cb_set_gmail_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    await q.message.reply_text(
        f"🔑 *Set Gmail App Password*\n\n"
        f"{DIVIDER}\n"
        "Enter your Gmail *App Password* (16-character code from Google).\n\n"
        "📌 *How to get it:*\n"
        "1. Go to Google Account → Security\n"
        "2. Under '2-Step Verification' → App Passwords\n"
        "3. Select 'Mail' and generate\n"
        "4. Copy the 16-character code\n\n"
        "_Example: `abcd efgh ijkl mnop`_\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_gmail_settings")]]
        ),
    )
    return GMAIL_PASS_INPUT


async def handle_gmail_pass_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    import gmail_checker as gc
    raw = update.message.text.strip().replace(" ", "")
    if len(raw) < 8:
        await update.message.reply_text("⚠️ App Password seems too short. Please check and try again:")
        return GMAIL_PASS_INPUT
    await db.set_setting("gmail_app_password", raw)
    gc.GMAIL_APP_PASSWORD = raw
    import gmail_checker
    gmail_checker.GMAIL_ADDRESS = await db.get_setting("gmail_address", gc.GMAIL_ADDRESS)
    gmail_checker.GMAIL_APP_PASSWORD = raw
    await update.message.reply_text(
        f"✅ *Gmail App Password Updated!*\n\n"
        f"{DIVIDER}\n"
        "Gmail verification is now *configured and ready*.\n\n"
        "Users can now use *Auto Verification* after making a payment.\n"
        "The bot will scan your inbox to confirm their UTR automatically.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 Gmail Settings", callback_data="a_gmail_settings")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="a_back")],
        ]),
    )
    return ConversationHandler.END


# ── Message User (direct message from admin) ──────────────────────────────────
async def cb_msguser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry: admin wants to message a specific user by ID/username."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    ctx.user_data.pop("msg_target_uid", None)
    await q.message.reply_text(
        f"✉️ *Message a User*\n\n"
        f"{DIVIDER}\n"
        f"Enter the *User ID* or *@username* of the user to message:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return MSG_USER_UID_INPUT


async def cb_msgtarget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quick 'Message User' from a user profile card (uid already known)."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_msgtarget_", ""))
    ctx.user_data["msg_target_uid"] = uid
    await q.message.reply_text(
        f"✉️ *Send Message to User `{uid}`*\n\n"
        f"Send any message — text, photo, video, or document:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return MSG_USER_BODY_INPUT


async def handle_msguser_uid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    target = update.message.text.strip().lstrip("@")
    users = await db.get_all_users()
    found = next((u for u in users if str(u["user_id"]) == target or u.get("username") == target), None)
    if not found:
        await update.message.reply_text("❌ User not found. Check the ID/username and try again:")
        return MSG_USER_UID_INPUT
    ctx.user_data["msg_target_uid"] = found["user_id"]
    name = f"@{found['username']}" if found.get("username") else f"`{found['user_id']}`"
    await update.message.reply_text(
        f"✅ Found user {name}\n\n"
        f"Now send the message to deliver:\n"
        f"_(any type: text, photo, video, document)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return MSG_USER_BODY_INPUT


async def handle_msguser_body(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    uid = ctx.user_data.pop("msg_target_uid", None)
    if not uid:
        await update.message.reply_text("⚠️ Session expired. Please start over.", reply_markup=admin_menu_kb())
        return ConversationHandler.END
    try:
        await ctx.bot.copy_message(
            chat_id=uid,
            from_chat_id=update.message.chat_id,
            message_id=update.message.message_id,
        )
        await update.message.reply_text(
            f"✅ *Message delivered to user `{uid}`!*",
            parse_mode="Markdown",
            reply_markup=admin_menu_kb(),
        )
    except Exception as ex:
        await update.message.reply_text(
            f"❌ *Could not send message:*\n`{ex}`\n\nThe user may have blocked the bot.",
            parse_mode="Markdown",
            reply_markup=admin_menu_kb(),
        )
    return ConversationHandler.END


# ── User profile quick-actions ─────────────────────────────────────────────────
async def cb_revoke_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_revokeprem_", ""))
    await db.revoke_premium(uid)
    try:
        await ctx.bot.send_message(
            chat_id=uid,
            text="ℹ️ *Your premium subscription has been revoked by an admin.*\n\nContact support if you think this is a mistake.",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await q.message.reply_text(
        f"✅ *Premium revoked* for user `{uid}`.",
        parse_mode="Markdown",
        reply_markup=back_kb(),
    )


async def cb_reset_user_sends(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_resetsends_", ""))
    await db.reset_user_sends(uid)
    free_limit = await db.get_free_limit()
    try:
        await ctx.bot.send_message(
            chat_id=uid,
            text=f"🔄 *Your free DM counter has been reset!*\n\nYou can now send up to *{free_limit}* free DMs again. 🎉",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await q.message.reply_text(
        f"✅ *Sends reset* for user `{uid}`.\nThey can now use their full *{free_limit}* free DMs again.",
        parse_mode="Markdown",
        reply_markup=back_kb(),
    )


async def cb_extend_prem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry: admin taps Extend/Grant Premium from a user profile card."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return
    uid = int(q.data.replace("a_extendprem_", ""))
    ctx.user_data["extend_prem_uid"] = uid
    is_active = await db.check_premium_active(uid)
    action = "Extend" if is_active else "Grant"
    await q.message.reply_text(
        f"🔰 *{action} Premium for `{uid}`*\n\n"
        f"How many days to add?\n"
        f"_(enter a number, e.g. `7`, `30`, `999` for lifetime)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="a_back")]]
        ),
    )
    return EXTEND_PREM_DAYS_INPUT


async def handle_extend_prem_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END
    uid = ctx.user_data.pop("extend_prem_uid", None)
    if not uid:
        await update.message.reply_text("⚠️ Session expired.", reply_markup=admin_menu_kb())
        return ConversationHandler.END
    raw = update.message.text.strip()
    try:
        days = int(raw)
        if days < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid number. Try again:")
        ctx.user_data["extend_prem_uid"] = uid
        return EXTEND_PREM_DAYS_INPUT

    await db.extend_premium(uid, days, plan_key="admin_grant")
    await db.increment_plans(uid)
    label = "Unlimited (Lifetime)" if days >= 999 else f"{days} day(s)"
    try:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"🎁 *Your premium has been extended!*\n\n"
                f"⏳ Duration added: *{label}*\n"
                "Enjoy unlimited DMs! 🚀"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ *{label} premium granted to user `{uid}`!*",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )
    return ConversationHandler.END


async def cb_admin_howto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comprehensive admin how-to guide — one message per section."""
    q = update.callback_query
    await q.answer()
    if not await admin_only(update):
        return

    sections = [
        # ── Overview ──────────────────────────────────────────────────────────
        (
            f"📖 *ADMIN PANEL — HOW TO USE*\n"
            f"{DIVIDER}\n\n"
            f"This is your complete guide to every feature in the Admin Dashboard.\n"
            f"Each section below covers a different panel.\n\n"
            f"*Sections covered:*\n"
            f"1️⃣  User Management\n"
            f"2️⃣  Payments & Revenue\n"
            f"3️⃣  Broadcast (All Message Types)\n"
            f"4️⃣  Premium & Gift Codes\n"
            f"5️⃣  Pricing / Plans\n"
            f"6️⃣  Bot Settings\n"
            f"7️⃣  Edit / Settings Panel\n"
            f"8️⃣  Referral System\n"
            f"9️⃣  Custom Buttons\n"
            f"🔟  Channel Promo Orders\n"
            f"1️⃣1️⃣  Maintenance Mode\n"
            f"1️⃣2️⃣  Analytics\n"
            f"1️⃣3️⃣  Gmail Auto-Pay Verification"
        ),
        # ── 1. User Management ────────────────────────────────────────────────
        (
            f"1️⃣ *USER MANAGEMENT*\n"
            f"{DIVIDER}\n\n"
            f"👥 *All Users*\n"
            f"  Shows every registered user in a paginated list with their ID,\n"
            f"  @username (if set), phone number, join date, and ban status.\n\n"
            f"🔍 *Search User*\n"
            f"  Type a Telegram User ID or @username to look up a specific user.\n"
            f"  The profile card shows their stats, plan, DMs sent, and account info.\n"
            f"  From the profile card you can:\n"
            f"  • 🚫/✅ Quick-ban or quick-unban\n"
            f"  • 🎁 Gift premium days directly\n"
            f"  • 🔰 Extend or grant premium\n"
            f"  • ❌ Revoke active premium\n"
            f"  • 🔄 Reset their free DM send counter\n"
            f"  • ✉️ Send them a direct message\n\n"
            f"🚫 *Ban User*\n"
            f"  Enter a User ID or @username. The user is immediately blocked from\n"
            f"  all bot features and receives a notification.\n\n"
            f"✅ *Unban User*\n"
            f"  Enter the same ID/username to restore access. User is notified.\n\n"
            f"📱 *Linked Users*\n"
            f"  Lists all users who have connected a Telegram account via the bot."
        ),
        # ── 2. Payments ───────────────────────────────────────────────────────
        (
            f"2️⃣ *PAYMENTS & REVENUE*\n"
            f"{DIVIDER}\n\n"
            f"⏳ *Pending Payments*\n"
            f"  Shows all UTR submissions awaiting your review.\n"
            f"  Each entry shows: User, Plan, Amount, UTR number, Order ID.\n"
            f"  Tap ✅ Approve → premium is activated instantly + user notified.\n"
            f"  Tap ❌ Reject  → user is notified that payment was declined.\n\n"
            f"💰 *All Payments*\n"
            f"  Full history of every payment (approved, pending, rejected).\n\n"
            f"📊 *Revenue Stats*\n"
            f"  Total revenue, conversion rate, and a breakdown by plan.\n\n"
            f"💳 *UPI Settings*\n"
            f"  View or change the UPI ID users pay to.\n"
            f"  A live QR code preview is generated immediately after saving.\n\n"
            f"📧 *Gmail Settings*\n"
            f"  Configure Gmail auto-pay verification:\n"
            f"  1. Enter the Gmail address that receives your UPI receipts.\n"
            f"  2. Enter the Gmail App Password (16-char code from Google).\n"
            f"  Once configured, UTRs are verified automatically — no manual review needed.\n"
            f"  If Gmail is not set up, all payments fall back to manual approval."
        ),
        # ── 3. Broadcast ──────────────────────────────────────────────────────
        (
            f"3️⃣ *BROADCAST*\n"
            f"{DIVIDER}\n\n"
            f"Send a message to all — or a subset of — your users.\n\n"
            f"*Step 1 — Choose audience:*\n"
            f"  📢 All Users     — every non-banned registered user\n"
            f"  👑 Premium Only  — only active premium subscribers\n"
            f"  🆓 Free Only     — only users on the free plan\n\n"
            f"*Step 2 — Send your message.*\n"
            f"  Any Telegram message type is supported:\n"
            f"  • Plain text (with bold, italic, code, links, spoilers)\n"
            f"  • Photos (with or without captions)\n"
            f"  • Videos (with or without captions)\n"
            f"  • GIFs / Animations\n"
            f"  • Documents & files\n"
            f"  • Audio, voice messages, video notes (round)\n"
            f"  • Stickers (including animated & premium)\n"
            f"  • Polls\n"
            f"  • Premium emoji\n"
            f"  • Forwarded messages (content is preserved exactly)\n\n"
            f"*Step 3 — Confirm.*\n"
            f"  The bot echoes your message as a preview and shows the recipient count.\n"
            f"  Tap *🚀 Yes — Send Broadcast Now* to deliver, or *❌ Cancel*.\n\n"
            f"*During broadcast:*\n"
            f"  A live progress bar updates every batch so you can track delivery.\n\n"
            f"*Final report shows:*\n"
            f"  ✅ Delivered  |  🚫 Blocked/Left  |  ❌ Failed  |  % delivery rate\n\n"
            f"⚠️ Users who have blocked the bot are automatically skipped and counted\n"
            f"as 'Blocked' — this is normal and does not indicate an error."
        ),
        # ── 4. Premium & Gift Codes ───────────────────────────────────────────
        (
            f"4️⃣ *PREMIUM & GIFT CODES*\n"
            f"{DIVIDER}\n\n"
            f"👑 *Premium Users*\n"
            f"  Lists all active premium subscribers with their plan key,\n"
            f"  expiry date, and days remaining.\n\n"
            f"🎁 *Gift Code — Create*\n"
            f"  3-step creation wizard:\n"
            f"  1. Enter the gift code text (alphanumeric, your choice)\n"
            f"  2. Choose duration:\n"
            f"     ⚡ 1 Day  |  🔥 3 Days  |  💎 7 Days  |  🏆 15 Days\n"
            f"     👑 1 Month  |  ♾️ Unlimited (Lifetime)\n"
            f"  3. Set max uses (1 = single-use, 999 = unlimited uses)\n"
            f"  Share the code with users — they redeem it in the user bot.\n\n"
            f"🎁 *Gift Premium from a User Profile*\n"
            f"  Search the user → tap *🎁 Gift* → enter number of days.\n"
            f"  Premium is added immediately and the user is notified.\n\n"
            f"🔰 *Extend Premium*\n"
            f"  From the user profile card, tap *🔰 Extend/Grant* and enter days.\n"
            f"  If the user already has premium, days are stacked on top.\n\n"
            f"❌ *Revoke Premium*\n"
            f"  From the user profile card — immediately ends their premium subscription."
        ),
        # ── 5. Pricing ────────────────────────────────────────────────────────
        (
            f"5️⃣ *PRICING / PLANS*\n"
            f"{DIVIDER}\n\n"
            f"💰 *Set Price* opens the plan manager:\n\n"
            f"✏️ *Edit an existing plan price*\n"
            f"  Tap the plan → enter the new price in ₹.\n"
            f"  Changes take effect immediately in the user bot.\n\n"
            f"➕ *Add a new plan*\n"
            f"  1. Enter the plan duration in days (e.g. `30` for 1 month)\n"
            f"  2. Enter the price in ₹\n"
            f"  The plan appears instantly in the user bot's premium screen.\n\n"
            f"🗑 *Remove a plan*\n"
            f"  Select the plan to delete. At least one plan must always remain.\n\n"
            f"⚠️ Existing premium users are NOT affected when you edit or remove plans —\n"
            f"  only new purchases use the updated prices."
        ),
        # ── 6. Bot Settings ───────────────────────────────────────────────────
        (
            f"6️⃣ *BOT SETTINGS*\n"
            f"{DIVIDER}\n\n"
            f"⚙️ *Bot Settings* panel controls global behaviour:\n\n"
            f"🆓 *Change Free Limit*\n"
            f"  Sets how many DMs a free-plan user can send per campaign.\n"
            f"  Default is 100. Enter any positive number.\n\n"
            f"🤝 *Toggle Referrals*\n"
            f"  Enable or disable the entire referral system.\n"
            f"  When OFF, no referral rewards are granted to anyone.\n\n"
            f"📛 *Set Bot Name*\n"
            f"  Sets the display name used in welcome messages and referral links.\n"
            f"  Max 64 characters.\n\n"
            f"💧 *Watermark ON/OFF*\n"
            f"  When ON, every DM sent through the bot appends:\n"
            f"  _\"This message was sent by @YourUsername.\"_\n"
            f"  Toggle this to enable or disable the watermark for all users.\n\n"
            f"✏️ *Set Watermark Username*\n"
            f"  The @username shown inside the watermark text.\n"
            f"  Enter with or without the @ symbol — both work."
        ),
        # ── 7. Edit / Settings ────────────────────────────────────────────────
        (
            f"7️⃣ *EDIT / SETTINGS PANEL*\n"
            f"{DIVIDER}\n\n"
            f"📣 *Force Join Channels*\n"
            f"  Users must join ALL listed channels before they can use the bot.\n"
            f"  ➕ Add: send the channel username (@MyChannel) or full invite link\n"
            f"  ➖ Remove: select from the list to delete\n"
            f"  Supports public channels, private invite links, and join-request channels.\n\n"
            f"👤 *Support Username*\n"
            f"  The @username shown when users tap 💬 Support.\n\n"
            f"💳 *UPI ID (Edit)*\n"
            f"  Alternate place to update the UPI payment address.\n\n"
            f"👑 *Add Admin*\n"
            f"  Enter a Telegram User ID to grant admin access to another person.\n"
            f"  Extra admins can use most admin features but cannot add/remove admins.\n\n"
            f"🗑 *Remove Admin*\n"
            f"  Select an extra admin from the list to revoke their access.\n\n"
            f"📋 *View All Admins*\n"
            f"  Lists the primary admin and all extra admins.\n\n"
            f"📝 *Edit Welcome Text*\n"
            f"  The message new users see when they first open the user bot.\n\n"
            f"🖼 *Change Welcome Image*\n"
            f"  Upload a new photo to show alongside the welcome message.\n\n"
            f"📷 *Change QR Image*\n"
            f"  Upload a fallback QR image shown if the auto-generated QR fails."
        ),
        # ── 8. Referral System ────────────────────────────────────────────────
        (
            f"8️⃣ *REFERRAL SYSTEM*\n"
            f"{DIVIDER}\n\n"
            f"🤝 *Referral Settings* panel:\n\n"
            f"⭐ *Set Reward Days*\n"
            f"  How many premium days a referrer earns per successful referral.\n"
            f"  Enter a number (e.g. `1` day per referral).\n\n"
            f"📊 *View All Referrals*\n"
            f"  Full table: referrer → referred user, status (pending/completed),\n"
            f"  and reward days earned.\n\n"
            f"*Referral rules (built-in, cannot be changed from settings):*\n"
            f"  • A referral is only completed when the referred user:\n"
            f"    1. Opens the bot via the referral link\n"
            f"    2. Links their Telegram account\n"
            f"    3. Runs at least one DM campaign\n"
            f"  • Users cannot refer themselves\n"
            f"  • Each user can only be referred once\n\n"
            f"🏅 *Milestone Bonuses (auto-applied):*\n"
            f"  5 refs → +1 day  |  10 refs → +3 days  |  15 refs → +7 days\n"
            f"  20 refs → +15 days  |  25 refs → +30 days"
        ),
        # ── 9. Custom Buttons ─────────────────────────────────────────────────
        (
            f"9️⃣ *CUSTOM BUTTONS*\n"
            f"{DIVIDER}\n\n"
            f"🔗 *Custom Buttons* lets you inject URL buttons into the user bot's\n"
            f"main menu — useful for promotions, links to your other bots, or any URL.\n\n"
            f"➕ *Add a button*\n"
            f"  1. Enter the button label (text shown on the button)\n"
            f"  2. Enter the URL (any https:// or t.me/ link)\n"
            f"  The button appears at the bottom of the main menu instantly.\n\n"
            f"➖ *Remove a button*\n"
            f"  Select from the list of existing custom buttons to delete it.\n"
            f"  Removal is immediate."
        ),
        # ── 10. Channel Promo Orders ──────────────────────────────────────────
        (
            f"🔟 *CHANNEL PROMO ORDERS*\n"
            f"{DIVIDER}\n\n"
            f"📣 *Promo Orders*\n"
            f"  Lists all channel member-growth orders submitted by users.\n"
            f"  Each order shows: User, channel link, member count, price/member,\n"
            f"  total amount, and submitted UTR.\n\n"
            f"  ✅ *Approve* — marks the order as fulfilled; user is notified.\n"
            f"  ❌ *Reject*  — declines the order; user is notified.\n\n"
            f"💸 *Set Promo Price / Member*\n"
            f"  Sets the global default price per member for channel promotion.\n"
            f"  Users see this as the starting reference price before the 50% discount.\n\n"
            f"⚠️ Approving a promo order does NOT automatically add members —\n"
            f"  you are responsible for fulfilling the order through your own service."
        ),
        # ── 11. Maintenance Mode ──────────────────────────────────────────────
        (
            f"1️⃣1️⃣ *MAINTENANCE MODE*\n"
            f"{DIVIDER}\n\n"
            f"🔧 Maintenance Mode blocks all regular users from using the bot.\n\n"
            f"🔴 *Turn ON*\n"
            f"  All user bot interactions are blocked immediately.\n"
            f"  Users see a maintenance message and cannot proceed.\n"
            f"  Admin access is NOT affected — you can still use the admin bot.\n\n"
            f"🟢 *Turn OFF*\n"
            f"  Restores full access for all users instantly.\n\n"
            f"*When to use:*\n"
            f"  • Deploying updates or making backend changes\n"
            f"  • Pausing the bot temporarily for any reason\n"
            f"  • Preventing new campaigns during maintenance windows"
        ),
        # ── 12. Analytics ─────────────────────────────────────────────────────
        (
            f"1️⃣2️⃣ *ANALYTICS*\n"
            f"{DIVIDER}\n\n"
            f"📈 *Analytics* shows a snapshot of bot-wide activity:\n\n"
            f"  👥 Total users & new users today\n"
            f"  👑 Active premium count\n"
            f"  📱 Linked Telegram accounts\n"
            f"  ✉️ Total DMs sent across all campaigns\n"
            f"  🔄 Currently active campaigns\n"
            f"  💰 Payments: approved count, pending count, total ₹ revenue\n"
            f"  📋 Revenue breakdown by plan\n"
            f"  📊 Conversion rate (approved ÷ total payments × 100)"
        ),
        # ── 13. Gmail Auto-Pay ────────────────────────────────────────────────
        (
            f"1️⃣3️⃣ *GMAIL AUTO-PAY VERIFICATION*\n"
            f"{DIVIDER}\n\n"
            f"The bot can verify UPI payments automatically by reading your Gmail inbox.\n\n"
            f"*How to set it up:*\n"
            f"  1. Enable 2-Step Verification on your Gmail account\n"
            f"  2. Go to Google Account → Security → App Passwords\n"
            f"  3. Generate a password for 'Mail' (16-char code)\n"
            f"  4. In Admin Panel → 📧 Gmail Settings:\n"
            f"     • Tap *✏️ Set Gmail Address* → enter your Gmail\n"
            f"     • Tap *🔑 Set App Password* → enter the 16-char code\n\n"
            f"*How it works:*\n"
            f"  When a user submits a UTR via *Automatic Pay*, the bot:\n"
            f"  1. Searches your inbox for emails from the last 5 days\n"
            f"  2. Looks for the UTR number AND the plan amount in the same email\n"
            f"  3. If both match → premium activated instantly, no manual review needed\n"
            f"  4. If not found → user can retry or switch to Manual approval\n\n"
            f"*Supported email senders:*\n"
            f"  GPay, PhonePe, Paytm, FamPay, bank NEFT/IMPS alerts, and any\n"
            f"  email containing the UTR in the subject or body.\n\n"
            f"⚠️ Use a Gmail that actually receives your UPI payment receipts.\n"
            f"⚠️ If Gmail is not configured, ALL payments require manual admin approval."
        ),
    ]

    for section in sections:
        await q.message.reply_text(section, parse_mode="Markdown")

    await q.message.reply_text(
        f"✅ *End of Admin Guide*\n\n"
        f"{DIVIDER}\n"
        f"Need help with something not covered here? Use ✉️ *Message User* to contact\n"
        f"a specific user, or set your own support @username in ⚙️ Edit / Settings.",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb(),
    )


def build_app():
    app = Application.builder().token(ADMIN_BOT_TOKEN).concurrent_updates(True).build()

    def conv(entry_cb, entry_pattern, state_id, handler_fn):
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(entry_cb, pattern=f"^{entry_pattern}$")],
            states={state_id: [MessageHandler(filters.ALL & ~filters.COMMAND, handler_fn)]},
            fallbacks=[CommandHandler("cancel", cancel_conv)],
            allow_reentry=True, per_message=False,
        )

    ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_ban, pattern="^a_ban$")],
        states={BAN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    unban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_unban, pattern="^a_unban$")],
        states={UNBAN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unban)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    gift_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_gift, pattern="^a_gift$"),
            CallbackQueryHandler(cb_giftuser, pattern="^a_giftuser_"),
        ],
        states={
            GIFT_CODE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_code_text),
            ],
            GIFT_DAYS_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_days_text),
            ],
            GIFT_MAXUSES_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_maxuses),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    broadcast_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_broadcast_all, pattern="^a_bc_all$"),
            CallbackQueryHandler(cb_broadcast_premium, pattern="^a_bc_premium$"),
            CallbackQueryHandler(cb_broadcast_free, pattern="^a_bc_free$"),
        ],
        states={
            BROADCAST_INPUT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_broadcast_preview),
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(cb_broadcast_send, pattern="^bc_confirm_send$"),
                CallbackQueryHandler(cb_broadcast_cancel, pattern="^bc_confirm_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    maintenance_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_maintenance, pattern="^a_maintenance$")],
        states={},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    welcome_img_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_upload_welcome_img, pattern="^ae_welcome_img$")],
        states={UPLOAD_WELCOME_IMG: [MessageHandler(filters.PHOTO, handle_upload_welcome_img)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    qr_img_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_upload_qr_img, pattern="^ae_qr_img$")],
        states={UPLOAD_QR_IMG: [MessageHandler(filters.PHOTO, handle_upload_qr_img)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    channel_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_channel_add, pattern="^ae_channel_add$")],
        states={EDIT_CHANNEL_ADD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_add)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_support, pattern="^ae_support$")],
        states={EDIT_SUPPORT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_support_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    upi_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_upi, pattern="^ae_upi$")],
        states={EDIT_UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_upi_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    set_upi_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_upi, pattern="^a_set_upi$")],
        states={SET_UPI_SETTINGS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_upi_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    admin_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_admin_add, pattern="^ae_admin_add$")],
        states={EDIT_ADMIN_ADD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_welcome, pattern="^ae_welcome$")],
        states={EDIT_WELCOME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_welcome_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_search, pattern="^a_search$")],
        states={USER_SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(ban_conv)
    app.add_handler(unban_conv)
    app.add_handler(gift_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(maintenance_conv)
    app.add_handler(channel_add_conv)
    app.add_handler(support_conv)
    app.add_handler(upi_conv)
    app.add_handler(set_upi_conv)
    app.add_handler(admin_add_conv)
    app.add_handler(welcome_conv)
    custom_btn_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_custom_btn_add, pattern="^acb_add$")],
        states={
            CUSTOM_BTN_LABEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_btn_label)],
            CUSTOM_BTN_URL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_btn_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )

    set_price_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_set_price_edit, pattern="^sp_edit_"),
            CallbackQueryHandler(cb_set_price_add, pattern="^sp_add$"),
        ],
        states={
            SET_PRICE_EDIT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_edit_input)
            ],
            SET_PRICE_NEW_DAYS_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_plan_days)
            ],
            SET_PRICE_NEW_PRICE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_plan_price)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )

    # ── New conversations ──────────────────────────────────────────────────────
    free_limit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_free_limit, pattern="^a_set_free_limit$")],
        states={FREE_LIMIT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_limit_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    msguser_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_msguser, pattern="^a_msguser$"),
            CallbackQueryHandler(cb_msgtarget, pattern="^a_msgtarget_"),
        ],
        states={
            MSG_USER_UID_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msguser_uid)],
            MSG_USER_BODY_INPUT: [MessageHandler(filters.ALL & ~filters.COMMAND, handle_msguser_body)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    extend_prem_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_extend_prem, pattern="^a_extendprem_")],
        states={EXTEND_PREM_DAYS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_extend_prem_days)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    bot_name_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_bot_name, pattern="^a_set_bot_name$")],
        states={BOT_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bot_name_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    watermark_username_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_watermark_username, pattern="^a_set_watermark_username$")],
        states={WATERMARK_USERNAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_watermark_username_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )

    app.add_handler(search_conv)
    app.add_handler(custom_btn_conv)
    app.add_handler(set_price_conv)
    app.add_handler(free_limit_conv)
    app.add_handler(msguser_conv)
    app.add_handler(extend_prem_conv)
    app.add_handler(bot_name_conv)
    app.add_handler(watermark_username_conv)
    app.add_handler(welcome_img_conv)
    app.add_handler(qr_img_conv)

    app.add_handler(CallbackQueryHandler(cb_set_price, pattern="^a_set_price$"))
    app.add_handler(CallbackQueryHandler(cb_set_price_remove, pattern="^sp_remove$"))
    app.add_handler(CallbackQueryHandler(cb_set_price_remove_confirm, pattern="^sp_del_"))
    app.add_handler(CallbackQueryHandler(cb_back, pattern="^a_back$"))
    app.add_handler(CallbackQueryHandler(cb_refresh, pattern="^a_refresh$"))
    app.add_handler(CallbackQueryHandler(cb_edit, pattern="^a_edit$"))
    app.add_handler(CallbackQueryHandler(cb_edit_channels, pattern="^ae_channels$"))
    app.add_handler(CallbackQueryHandler(cb_channel_remove, pattern="^ae_channel_remove$"))
    app.add_handler(CallbackQueryHandler(cb_channel_remove_confirm, pattern="^ae_rmch_"))
    app.add_handler(CallbackQueryHandler(cb_edit_admin_remove, pattern="^ae_admin_remove$"))
    app.add_handler(CallbackQueryHandler(cb_admin_remove_confirm, pattern="^ae_rmadmin_"))
    app.add_handler(CallbackQueryHandler(cb_admin_list, pattern="^ae_admin_list$"))
    app.add_handler(CallbackQueryHandler(cb_users, pattern="^a_users$"))
    app.add_handler(CallbackQueryHandler(cb_revenue, pattern="^a_revenue$"))
    app.add_handler(CallbackQueryHandler(cb_pending, pattern="^a_pending$"))
    app.add_handler(CallbackQueryHandler(cb_allpayments, pattern="^a_allpayments$"))
    app.add_handler(CallbackQueryHandler(cb_approve, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(cb_reject, pattern="^pay_reject_"))
    app.add_handler(CallbackQueryHandler(cb_quickban, pattern="^a_quickban_"))
    app.add_handler(CallbackQueryHandler(cb_quickunban, pattern="^a_quickunban_"))
    app.add_handler(CallbackQueryHandler(cb_custom_buttons, pattern="^a_custom_buttons$"))
    app.add_handler(CallbackQueryHandler(cb_custom_btn_remove, pattern="^acb_remove$"))
    app.add_handler(CallbackQueryHandler(cb_custom_btn_remove_confirm, pattern="^acb_del_"))
    app.add_handler(CallbackQueryHandler(cb_referral_settings, pattern="^a_referral$"))
    app.add_handler(CallbackQueryHandler(cb_referral_stats, pattern="^a_referral_stats$"))
    # ── New simple callbacks ───────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_broadcast, pattern="^a_broadcast$"))
    app.add_handler(CallbackQueryHandler(cb_admin_howto, pattern="^a_howto$"))
    app.add_handler(CallbackQueryHandler(cb_analytics, pattern="^a_analytics$"))
    app.add_handler(CallbackQueryHandler(cb_premium_users, pattern="^a_premiumusers$"))
    app.add_handler(CallbackQueryHandler(cb_botsettings, pattern="^a_botsettings$"))
    app.add_handler(CallbackQueryHandler(cb_toggle_referrals, pattern="^a_toggle_referrals$"))
    app.add_handler(CallbackQueryHandler(cb_toggle_watermark, pattern="^a_toggle_watermark$"))
    app.add_handler(CallbackQueryHandler(cb_revoke_premium, pattern="^a_revokeprem_"))
    app.add_handler(CallbackQueryHandler(cb_reset_user_sends, pattern="^a_resetsends_"))
    app.add_handler(CallbackQueryHandler(cb_maintenance_on, pattern="^a_maintenance_on$"))
    app.add_handler(CallbackQueryHandler(cb_maintenance_off, pattern="^a_maintenance_off$"))
    app.add_handler(CallbackQueryHandler(cb_linked_users, pattern="^a_linked_users$"))
    app.add_handler(CallbackQueryHandler(cb_upi_settings, pattern="^a_upi_settings$"))
    app.add_handler(CallbackQueryHandler(cb_gmail_settings, pattern="^a_gmail_settings$"))

    gmail_email_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_gmail_email, pattern="^a_set_gmail_email$")],
        states={GMAIL_EMAIL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gmail_email_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    gmail_pass_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_gmail_pass, pattern="^a_set_gmail_pass$")],
        states={GMAIL_PASS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gmail_pass_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    app.add_handler(gmail_email_conv)
    app.add_handler(gmail_pass_conv)

    referral_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_referral_set_reward, pattern="^a_ref_set_reward$")],
        states={REFERRAL_REWARD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_referral_reward_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    app.add_handler(referral_conv)

    # ── Channel Promo Promo Price conv ─────────────────────────────────────────
    promo_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_promo_price, pattern="^a_set_promo_price$")],
        states={PROMO_PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_promo_price)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True, per_message=False,
    )
    app.add_handler(promo_price_conv)
    app.add_handler(CallbackQueryHandler(cb_promo_orders, pattern="^a_promo_orders$"))
    app.add_handler(CallbackQueryHandler(cb_promo_approve, pattern="^promo_approve_"))
    app.add_handler(CallbackQueryHandler(cb_promo_reject, pattern="^promo_reject_"))

    return app
