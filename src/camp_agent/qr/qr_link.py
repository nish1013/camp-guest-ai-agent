from datetime import date, timedelta

from camp_agent.qr.qr_token import QrTokens


def demo_link(tokens: QrTokens, base_url: str, cabin: str, today: date, nights: int) -> str:
    token = tokens.issue(cabin, today, today + timedelta(days=nights))
    return f"{base_url.rstrip('/')}/q/{token}"
