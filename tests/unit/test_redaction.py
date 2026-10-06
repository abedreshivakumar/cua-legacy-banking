"""S13: Luhn validation and text-redaction pattern unit tests. No
browser, no server — pure logic."""

from cua.safety.redaction import luhn_valid, redact_text


def test_luhn_valid_accepts_a_real_test_card_number() -> None:
    assert luhn_valid("4111111111111111") is True  # a well-known Visa test number


def test_luhn_valid_rejects_a_non_luhn_digit_run() -> None:
    assert luhn_valid("123456789012") is False


def test_luhn_valid_rejects_short_or_non_numeric_input() -> None:
    assert luhn_valid("123") is False
    assert luhn_valid("abcd1234efgh5678") is False


def test_redact_text_masks_a_dob() -> None:
    out = redact_text("Name: Ivy Mockington DOB: 1978-04-17 Status: ACTIVE")
    assert "1978-04-17" not in out
    assert "[REDACTED:DOB]" in out


def test_redact_text_masks_an_ssn() -> None:
    out = redact_text("SSN: 123-45-6789 on file")
    assert "123-45-6789" not in out
    assert "[REDACTED:SSN]" in out


def test_redact_text_masks_a_luhn_valid_account_number_but_not_a_plain_id() -> None:
    out = redact_text("acct=4111111111111111 ref=100000000000")
    assert "4111111111111111" not in out
    assert "[REDACTED:ACCT]" in out
    assert "100000000000" in out  # 12 digits but fails Luhn — not a real account/card shape


def test_redact_text_masks_a_declared_literal_even_without_a_pattern_match() -> None:
    out = redact_text("member_no=100007 was queried", sensitive_literals=["100007"])
    assert "100007" not in out
    assert "[REDACTED:DECLARED]" in out


def test_redact_text_leaves_ordinary_text_alone() -> None:
    text = "Member inquiry completed successfully for the active account."
    assert redact_text(text) == text
