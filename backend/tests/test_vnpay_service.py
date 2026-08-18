"""Self-consistency tests for vnpay_service.py's HMAC-SHA512 signing.

No live VNPay sandbox is configured yet (see plan
260818-vnpay-payment-and-email-confirmation's "Việc cần chuẩn bị" section),
so these can't be checked against VNPay's own published examples — they
instead pin down the properties that must hold regardless: signing is
deterministic, verification accepts a correctly-signed payload and rejects
any tampering, and the built URL/query shape matches what VNPay's API
expects. Re-verify against VNPay's own sample values once real credentials
exist.
"""

from decimal import Decimal

from src.services import vnpay_service


def test_sign_is_deterministic_and_order_independent():
    params_a = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000", "vnp_Command": "pay"}
    params_b = {"vnp_Command": "pay", "vnp_Amount": "10000000", "vnp_TxnRef": "abc123"}

    assert vnpay_service.sign(params_a, "secret") == vnpay_service.sign(params_b, "secret")


def test_sign_excludes_the_hash_fields_themselves():
    base = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000"}
    with_hash = {**base, "vnp_SecureHash": "whatever", "vnp_SecureHashType": "HmacSHA512"}

    assert vnpay_service.sign(base, "secret") == vnpay_service.sign(with_hash, "secret")


def test_sign_changes_if_any_value_changes():
    base = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000"}
    tampered = {"vnp_TxnRef": "abc123", "vnp_Amount": "99999999"}

    assert vnpay_service.sign(base, "secret") != vnpay_service.sign(tampered, "secret")


def test_verify_signature_accepts_a_correctly_signed_payload():
    params = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000", "vnp_ResponseCode": "00"}
    params["vnp_SecureHash"] = vnpay_service.sign(params, "secret")

    assert vnpay_service.verify_signature(params, "secret") is True


def test_verify_signature_rejects_a_tampered_amount():
    """The core anti-fraud property: a forged IPN/return-URL hit that
    changes vnp_Amount after the hash was computed must be caught, not
    silently trusted (routes.py's vnpay_ipn relies on this)."""
    params = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000", "vnp_ResponseCode": "00"}
    params["vnp_SecureHash"] = vnpay_service.sign(params, "secret")

    params["vnp_Amount"] = "1"  # attacker lowers the paid amount after signing
    assert vnpay_service.verify_signature(params, "secret") is False


def test_verify_signature_rejects_the_wrong_secret():
    params = {"vnp_TxnRef": "abc123", "vnp_Amount": "10000000"}
    params["vnp_SecureHash"] = vnpay_service.sign(params, "secret-a")

    assert vnpay_service.verify_signature(params, "secret-b") is False


def test_verify_signature_rejects_a_missing_hash():
    assert vnpay_service.verify_signature({"vnp_TxnRef": "abc123"}, "secret") is False


def test_build_payment_url_converts_amount_to_vnpay_wire_format():
    """VNPay's vnp_Amount has no decimal places — it's the real amount x100."""
    url = vnpay_service.build_payment_url(
        pay_url="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        tmn_code="TESTCODE",
        hash_secret="secret",
        amount=Decimal("1500000"),
        txn_ref="abc123",
        order_info="Thanh toan don hang abc123",
        return_url="https://example.com/return",
        ip_addr="127.0.0.1",
    )

    assert "vnp_Amount=150000000" in url
    assert url.startswith("https://sandbox.vnpayment.vn/paymentv2/vpcpay.html?")
    assert "vnp_SecureHash=" in url
    assert "vnp_TmnCode=TESTCODE" in url


def test_build_payment_url_is_self_verifiable():
    """The URL this function builds must pass its own verify_signature —
    otherwise VNPay (which runs the identical check) would reject every
    payment we ever create."""
    url = vnpay_service.build_payment_url(
        pay_url="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        tmn_code="TESTCODE",
        hash_secret="secret",
        amount=Decimal("250000"),
        txn_ref="txn-999",
        order_info="order",
        return_url="https://example.com/return",
        ip_addr="127.0.0.1",
    )

    query = url.split("?", 1)[1]
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(query))
    assert vnpay_service.verify_signature(params, "secret") is True


def test_vnpay_amount_to_decimal_is_the_inverse_conversion():
    assert vnpay_service.vnpay_amount_to_decimal("150000000") == Decimal("1500000")
