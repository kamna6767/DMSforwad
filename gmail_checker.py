"""
Gmail IMAP checker for automatic UPI payment verification.
Reads GMAIL_ADDRESS and GMAIL_APP_PASSWORD from environment.

Verification logic:
  - Searches the last 10–20 emails from any payment source (UPI, bank alerts,
    GPay, PhonePe, Paytm, FamPay, NEFT/IMPS confirmations, etc.)
  - A payment is verified if BOTH conditions are met:
      1. The submitted UTR / Transaction ID appears in the email text
      2. The plan amount appears in the email text
  - Returns a VerifyResult with details for transparent user feedback.
"""
import imaplib
import email as email_lib
import re
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# ── Payment-related senders / subjects to search ──────────────────────────────
_PAYMENT_SEARCH_QUERIES_TEMPLATE = [
    # Popular UPI & payment apps
    '(SINCE {date} SUBJECT "payment")',
    '(SINCE {date} SUBJECT "received")',
    '(SINCE {date} SUBJECT "transaction")',
    '(SINCE {date} SUBJECT "transfer")',
    '(SINCE {date} SUBJECT "credited")',
    '(SINCE {date} SUBJECT "debited")',
    '(SINCE {date} SUBJECT "utr")',
    '(SINCE {date} SUBJECT "upi")',
    # Common payment senders
    '(SINCE {date} FROM "gpay")',
    '(SINCE {date} FROM "phonepe")',
    '(SINCE {date} FROM "paytm")',
    '(SINCE {date} FROM "fampay")',
    '(SINCE {date} FROM "noreply@")',
    '(SINCE {date} FROM "alerts@")',
    '(SINCE {date} FROM "no-reply@")',
    # Direct ID search (catches anything)
    '(SINCE {date} BODY "{id}")',
]

# How many days back to look
_LOOKBACK_DAYS = 5

# Maximum emails to check (safety cap)
_MAX_EMAILS = 25


@dataclass
class VerifyResult:
    matched: bool
    reason: str = ""
    email_subject: str = ""


def _connect() -> imaplib.IMAP4_SSL:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials not configured.")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    return mail


def _extract_text(msg) -> str:
    """Extract all readable text from an email message."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    raw = part.get_payload(decode=True)
                    parts.append(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    pass
    else:
        try:
            raw = msg.get_payload(decode=True)
            parts.append(raw.decode("utf-8", errors="ignore"))
        except Exception:
            pass
    return " ".join(parts)


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _id_present(submitted: str, full_text: str) -> bool:
    """
    True if the submitted UTR / transaction ID appears in the email.
    Handles:
      - Exact substring match (case-insensitive)
      - Whitespace / punctuation around the ID
      - Token-level match among alphanumeric sequences
    """
    sub = _normalize(submitted)
    text = _normalize(full_text)

    # Direct substring match
    if sub in text:
        return True

    # Match with non-alphanumeric boundary characters stripped
    clean_sub = re.sub(r"[^a-z0-9]", "", sub)
    if not clean_sub:
        return False

    # Extract all alphanumeric tokens of similar length and compare
    tokens = re.findall(r"[a-z0-9]{6,}", text)
    for tok in tokens:
        if tok == clean_sub:
            return True

    return False


def _amount_present(amount: int, full_text: str) -> bool:
    """
    True if the plan amount (in INR) appears in the email in any common format.
    Handles: ₹10, Rs. 10, INR 10, 10.00, 10, etc.
    """
    text = _normalize(full_text)
    a = str(amount)

    candidates = [
        a,
        f"₹{a}",
        f"₹ {a}",
        f"rs.{a}", f"rs. {a}", f"rs {a}",
        f"inr{a}", f"inr {a}", f"inr. {a}", f"inr.{a}",
        f"{a}.00",
        f"₹{a}.00",
        f"rs.{a}.00", f"rs {a}.00",
        f"inr {a}.00",
        f"inr{a}.00",
    ]
    for c in candidates:
        if c.lower() in text:
            return True

    # Regex: digit boundary match (avoids matching "100" inside "1000")
    pattern = r"(?<!\d)" + re.escape(a) + r"(?!\d)"
    if re.search(pattern, text):
        # Make sure it's in a payment-money context
        money_context = re.compile(
            r"(?:₹|rs\.?|inr|amount|paid|credited|debited|transfer)"
            r".{0,20}"
            + re.escape(a)
            + r"|"
            + re.escape(a)
            + r".{0,20}(?:₹|rs\.?|inr|amount|paid|credited|debited)"
        )
        if money_context.search(text):
            return True

    return False


def check_payment(submitted_id: str, amount: int) -> VerifyResult:
    """
    Search Gmail for a payment email matching submitted_id AND amount.

    Returns a VerifyResult with .matched=True on success.
    This function is blocking (IMAP) — run via run_in_executor.
    """
    submitted_id = submitted_id.strip()

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not set — auto-pay verification cannot run.")
        return VerifyResult(
            matched=False,
            reason="gmail_not_configured",
        )

    try:
        mail = _connect()
        mail.select("inbox")

        since_date = (datetime.now() - timedelta(days=_LOOKBACK_DAYS)).strftime("%d-%b-%Y")

        # Collect unique email IDs matching any of our broad search queries
        collected_ids: set[bytes] = set()
        for tmpl in _PAYMENT_SEARCH_QUERIES_TEMPLATE:
            query = tmpl.format(date=since_date, id=submitted_id)
            try:
                status, messages = mail.search(None, query)
                if status == "OK" and messages[0]:
                    for mid in messages[0].split():
                        collected_ids.add(mid)
                        if len(collected_ids) >= _MAX_EMAILS:
                            break
            except Exception:
                continue
            if len(collected_ids) >= _MAX_EMAILS:
                break

        logger.info(
            f"Payment check: {len(collected_ids)} candidate email(s) "
            f"for id={submitted_id!r} amount=₹{amount}"
        )

        # Sort newest first (higher IDs are more recent in IMAP)
        sorted_ids = sorted(collected_ids, reverse=True)

        id_found = False  # Did we find the UTR but wrong amount?

        for email_id in sorted_ids:
            try:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw_bytes)
                subject = str(msg.get("Subject", ""))
                body = _extract_text(msg)
                full_text = body + " " + subject

                if not _id_present(submitted_id, full_text):
                    continue

                id_found = True

                if _amount_present(amount, full_text):
                    logger.info(
                        f"Payment MATCHED: id={submitted_id!r} amount=₹{amount} "
                        f"email_id={email_id} subject={subject!r}"
                    )
                    mail.logout()
                    return VerifyResult(
                        matched=True,
                        reason="matched",
                        email_subject=subject,
                    )
                else:
                    logger.info(
                        f"Payment ID found but amount ₹{amount} not present: "
                        f"id={submitted_id!r} subject={subject!r}"
                    )

            except Exception as ex:
                logger.warning(f"Error reading email {email_id}: {ex}")
                continue

        mail.logout()

        if id_found:
            # UTR matched but amount didn't — likely wrong amount or plan mismatch
            logger.info(f"Payment check: ID found but amount mismatch for id={submitted_id!r}")
            return VerifyResult(matched=False, reason="amount_mismatch")

        logger.info(f"Payment check: no match for id={submitted_id!r} amount=₹{amount}")
        return VerifyResult(matched=False, reason="not_found")

    except RuntimeError as ex:
        return VerifyResult(matched=False, reason="gmail_not_configured")
    except imaplib.IMAP4.error as ex:
        logger.error(f"Gmail IMAP login failed: {ex}")
        return VerifyResult(matched=False, reason="gmail_auth_error")
    except Exception as ex:
        logger.error(f"Gmail check failed: {ex}")
        return VerifyResult(matched=False, reason="error")


# Keep old name as alias for backwards compatibility
def check_fampay_payment(submitted_id: str, amount: int) -> bool:
    return check_payment(submitted_id, amount).matched
