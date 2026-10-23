"""Run as root in an interactive SSH terminal. Secrets are hidden and stay on the server."""
import getpass
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gongsi.api import ApiError, Telegram, now_kst, request_json

CONFIG = Path("/etc/gongsi/gongsi.env")
OWNER = 6766930417

def build_environment(token, dart_key):
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("Invalid Telegram bot token format")
    if not re.fullmatch(r"[A-Za-z0-9]{40}", dart_key):
        raise ValueError("OpenDART key must contain 40 alphanumeric characters")
    return (
        f"TELEGRAM_BOT_TOKEN={token}\nDART_API_KEY={dart_key}\n"
        f"TELEGRAM_OWNER_ID={OWNER}\nTELEGRAM_BOT_USERNAME=auto_dart_gongsi_bot\n"
        "POLL_SECONDS=300\nDART_DAILY_LIMIT=18000\n"
        "STATE_DIR=/var/lib/gongsi\nREADY_FILE=/run/gongsi/ready\n"
        "PYTHONDONTWRITEBYTECODE=1\n"
    )

def verify(token, dart_key):
    tg = Telegram(token)
    if tg.call("getMe").get("username") != "auto_dart_gongsi_bot":
        raise ValueError("Token belongs to another bot")
    chat = tg.call("getChat", chat_id=OWNER)
    if chat.get("id") != OWNER or chat.get("type") != "private":
        raise ValueError("Private recipient chat verification failed")
    if tg.call("getWebhookInfo").get("url"):
        raise ValueError("Existing webhook detected; review it before switching to long polling")
    today = now_kst().strftime("%Y%m%d")
    result = request_json("OpenDART", "https://opendart.fss.or.kr/api/list.json?" + urlencode(
        {"crtfc_key": dart_key, "bgn_de": today, "end_de": today, "page_count": 1}))
    if result.get("status") not in ("000", "013"):
        raise ApiError("OpenDART", result.get("status", "invalid"))

def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise ValueError("Run as root in an interactive terminal (ssh -t)")
    existing = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                existing[key] = value
    print("Enter the bot token and DART key here. Input is hidden; do not paste them into ChatGPT.")
    keep = " (Enter keeps existing)" if existing.get("TELEGRAM_BOT_TOKEN") else ""
    token = getpass.getpass("Telegram bot token" + keep + ": ").strip() or existing.get("TELEGRAM_BOT_TOKEN", "")
    keep = " (Enter keeps existing)" if existing.get("DART_API_KEY") else ""
    dart_key = getpass.getpass("OpenDART key" + keep + ": ").strip() or existing.get("DART_API_KEY", "")
    contents = build_environment(token, dart_key)
    verify(token, dart_key)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG.parent, delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            output.write(contents)
        os.replace(temporary, CONFIG)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("CONFIG OK: bot identity, recipient and DART API verified. Credentials saved on Oracle only.")

if __name__ == "__main__":
    try:
        main()
    except (ApiError, ValueError) as exc:
        print("CONFIG FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print("CONFIG FAILED: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

