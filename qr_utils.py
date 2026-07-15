"""Dynamic UPI QR code generator — production-quality, white background."""
from __future__ import annotations
from io import BytesIO
import urllib.parse


def generate_upi_qr(
    upi_id: str,
    amount: int | float,
    order_id: str,
    merchant_name: str = "AutoDMs Bot",
) -> bytes:
    """
    Return raw PNG bytes of a clean white-background UPI QR code.

    The UPI deep-link encodes:
      pa  — payee UPI address (the configured UPI ID)
      pn  — payee display name
      am  — exact amount in INR
      cu  — currency (always INR)
      tn  — transaction note (order ID for traceability)

    The QR is high-error-correction (level H) so it stays scannable
    even if apps render it slightly distorted.
    """
    import qrcode  # type: ignore

    # Format amount: no trailing zeros for whole numbers, 2dp otherwise
    if isinstance(amount, float) and amount != int(amount):
        amount_str = f"{amount:.2f}"
    else:
        amount_str = str(int(amount))

    upi_url = (
        "upi://pay?"
        + urllib.parse.urlencode({
            "pa": upi_id,
            "pn": merchant_name,
            "am": amount_str,
            "cu": "INR",
            "tn": order_id,
        })
    )

    qr = qrcode.QRCode(
        version=None,                          # auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,                           # larger boxes → easier to scan
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def validate_upi_id(upi_id: str) -> tuple[bool, str]:
    """
    Basic UPI ID format validation.
    A valid UPI ID is  localpart@provider  where:
      - localpart  is non-empty (mobile number, email prefix, or custom handle)
      - provider   is a non-empty bank/PSP suffix (okicici, paytm, upi, etc.)

    Returns (is_valid, error_message).
    """
    upi_id = upi_id.strip()
    if "@" not in upi_id:
        return False, "UPI ID must contain `@` (e.g. `name@upi`, `9876543210@paytm`)"
    parts = upi_id.split("@")
    if len(parts) != 2:
        return False, "UPI ID must have exactly one `@` symbol"
    local, provider = parts
    if not local:
        return False, "The part before `@` cannot be empty"
    if not provider:
        return False, "The part after `@` (bank/PSP name) cannot be empty"
    if len(upi_id) > 128:
        return False, "UPI ID is too long"
    return True, ""
