"""VNPay payment-gateway signing (plan 260818-vnpay-payment-and-email-confirmation).

VNPay's "Payment via Payment Platform" integration has two signed
touchpoints, both using the same HMAC-SHA512 scheme:
  1. build_payment_url() — the merchant signs an outbound redirect URL.
  2. verify_signature() — the merchant re-derives the same hash from an
     inbound request (the browser's return-URL hit, or the trusted IPN
     webhook) and compares it to the vnp_SecureHash VNPay sent back.

Signing recipe (matches VNPay's official PHP/Node sample code): take every
non-empty vnp_* param except vnp_SecureHash/vnp_SecureHashType, sort by key
(plain ASCII sort), URL-encode each key/value with '+' for spaces (PHP's
urlencode() semantics — Python's urllib.parse.quote_plus, NOT quote, which
would emit %20 instead and produce a different hash), join as
"k1=v1&k2=v2...", then HMAC-SHA512 that string with vnp_HashSecret.

Verified 2026-08-18 against the real sandbox: a build_payment_url() output
using the live vnp_TmnCode/vnp_HashSecret was opened in a real browser and
rendered VNPay's actual VNPayQR page with the correct order amount/ref —
confirming the signature, field set and ordering match VNPay's live
sandbox, not just the self-consistency unit tests (test_vnpay_service.py).
Still unverified: the IPN round-trip (mark_payment_paid/confirm_booking
path in routes.py's /payments/vnpay/ipn), which needs a publicly
reachable URL registered in VNPay's merchant portal — localhost can't
receive it, so this needs a tunnel (ngrok) or a public staging deploy
before it can be exercised for real.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
VNPAY_VERSION = "2.1.0"


def _hash_data(params: dict[str, str]) -> str:
    """The exact string VNPay signs: sorted, urlencoded key=value pairs,
    excluding the hash fields themselves and any empty value (VNPay's
    reference implementation drops empty params rather than including them
    as `key=`)."""
    items = sorted(
        (k, v) for k, v in params.items()
        if v not in (None, "") and k not in ("vnp_SecureHash", "vnp_SecureHashType")
    )
    return "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in items)


def sign(params: dict[str, str], hash_secret: str) -> str:
    """HMAC-SHA512 of _hash_data(params), hex-encoded — VNPay's vnp_SecureHash."""
    data = _hash_data(params)
    return hmac.new(hash_secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha512).hexdigest()


def verify_signature(params: dict[str, str], hash_secret: str) -> bool:
    """True iff params['vnp_SecureHash'] matches what we'd compute ourselves
    — the ONLY thing that makes a return-URL hit or an IPN call trustworthy.
    Constant-time compare (hmac.compare_digest) so this can't leak timing
    information about the real hash to a forged request."""
    received = str(params.get("vnp_SecureHash", ""))
    if not received:
        return False
    computed = sign(params, hash_secret)
    return hmac.compare_digest(computed.lower(), received.lower())


def build_payment_url(
    *,
    pay_url: str,
    tmn_code: str,
    hash_secret: str,
    amount: Decimal,
    txn_ref: str,
    order_info: str,
    return_url: str,
    ip_addr: str,
    locale: str = "vn",
    expire_minutes: int = 15,
) -> str:
    """Builds the signed VNPay redirect URL for one payment attempt.

    `amount` is real VND (e.g. Decimal("1500000")) — VNPay's own wire format
    multiplies by 100 (no decimal places), converted here so every other
    layer of this app keeps working in real currency units.
    `txn_ref` must be unique per attempt; this app uses the `payments.id`
    UUID with dashes stripped (VNPay's docs cap vnp_TxnRef length and
    recommend alnum-only).
    """
    now = datetime.now(VN_TZ)
    expire = now + timedelta(minutes=expire_minutes)
    params = {
        "vnp_Version": VNPAY_VERSION,
        "vnp_Command": "pay",
        "vnp_TmnCode": tmn_code,
        "vnp_Amount": str(int(round(amount * 100))),
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": txn_ref,
        "vnp_OrderInfo": order_info,
        "vnp_OrderType": "other",
        "vnp_Locale": locale,
        "vnp_ReturnUrl": return_url,
        "vnp_IpAddr": ip_addr,
        "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
        "vnp_ExpireDate": expire.strftime("%Y%m%d%H%M%S"),
    }
    secure_hash = sign(params, hash_secret)
    query = "&".join(f"{quote_plus(k)}={quote_plus(v)}" for k, v in sorted(params.items()))
    return f"{pay_url}?{query}&vnp_SecureHash={secure_hash}"


def vnpay_amount_to_decimal(vnp_amount: str) -> Decimal:
    """Inverse of the ×100 conversion above — for comparing an IPN's
    vnp_Amount against the payment row's stored amount."""
    return Decimal(vnp_amount) / 100
