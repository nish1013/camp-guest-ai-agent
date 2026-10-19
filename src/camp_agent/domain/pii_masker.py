import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_BOOKING_REF = re.compile(r"\bBK[-\s]?\d{4,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d")
_PHONE_MIN_DIGITS = 9


def mask_pii(text: str) -> str:
    masked = _EMAIL.sub("[email]", text)
    masked = _BOOKING_REF.sub("[ref]", masked)
    return _PHONE.sub(_mask_phone, masked)


def _mask_phone(match: re.Match[str]) -> str:
    digits = sum(char.isdigit() for char in match.group())
    return "[phone]" if digits >= _PHONE_MIN_DIGITS else match.group()
