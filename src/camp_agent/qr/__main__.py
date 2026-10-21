import argparse
from zoneinfo import ZoneInfo

from camp_agent.clock import SystemClock
from camp_agent.config import Settings
from camp_agent.qr.qr_token import QrTokens, demo_link

# Prints the link a cabin QR code holds, signed with SECRET_KEY, for a stay from today.
parser = argparse.ArgumentParser(prog="python -m camp_agent.qr")


parser.add_argument("cabin")


parser.add_argument("--nights", type=int, default=6)


parser.add_argument("--base-url", default="http://localhost:8000")


args = parser.parse_args()


settings = Settings()


today = SystemClock(ZoneInfo(settings.camp_timezone)).today()


print(demo_link(QrTokens(settings.secret_key), args.base_url, args.cabin, today, args.nights))
