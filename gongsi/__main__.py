"""Two independent loops: responsive menu updates and a 5-minute DART poller."""
import logging
import os
import signal
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from .api import ApiError, Dart, Telegram, now_kst
from .bot import Bot
from .catalog import matches
from .storage import Store
from .extraction import Extractor, format_notification
from .test_replay import process_requests
from .runtime_reports import Publisher,send_recorded
from .api_diagnostics import run_probe

LOG = logging.getLogger("gongsi")

def scan(dart, store):
    today = now_kst().date()
    previous = store.get("last_scan_day")
    start = date.fromisoformat(previous) - timedelta(days=1) if previous else today - timedelta(days=1)
    # Bound catch-up work per iteration; later iterations advance without dropping old days.
    end = min(today, start + timedelta(days=30))
    reports = dart.reports(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    baseline = store.ingest(reports, end.isoformat(), matches)
    store.set("last_scan_success", now_kst().isoformat(timespec="seconds"))
    store.set("last_scan_error", "")
    LOG.info("DART scan complete; reports=%s baseline=%s through=%s", len(reports), baseline, end)
    return baseline

def deliver(bot, store, stop):
    for report in store.pending(limit=5):
        if stop.is_set():
            return
        prefs = store.settings()
        if prefs["paused"]:
            return
        if not matches(report["report_nm"], prefs["selected"]):
            store.acknowledge(report["rcept_no"])
            continue
        summary = None
        extractor = getattr(bot, 'extractor', None)
        if extractor is not None:
            try:
                summary = extractor.extract(report)
            except Exception:
                summary = {'source':'추출 불가 · 원문 확인','fields':[]}
        send_recorded(bot,store,report,summary,format_notification(report, summary, html=True),"notification")
        # Telegram has no sendMessage idempotency key: a crash before this commit can repeat a message.
        store.acknowledge(report["rcept_no"])
        if stop.wait(1.1):
            return

def worker(dart, bot, store, stop, interval):
    publisher = Publisher(store)
    next_scan = 0.0
    next_delivery = 0.0
    while not stop.is_set():
        if time.monotonic() >= next_scan:
            try:
                scan(dart, store)
            except Exception as exc:
                safe = str(exc) if isinstance(exc, ApiError) else type(exc).__name__
                store.set("last_scan_error", safe)
                LOG.error("DART scan failed: %s", safe)
            next_scan = time.monotonic() + interval
        if time.monotonic() >= next_delivery:
            delay = 5
            try:
                deliver(bot, store, stop)
                process_requests(bot, store, stop)
            except Exception as exc:
                # Never log raw network exceptions: their URLs may contain tokens.
                safe = str(exc) if isinstance(exc, ApiError) else type(exc).__name__
                LOG.error("Delivery failed: %s", safe)
                delay = max(5, exc.retry_after) if isinstance(exc, ApiError) else 5
            next_delivery = time.monotonic() + delay
        try:
            run_probe(bot,store)
        except Exception as exc:
            LOG.warning('API diagnostic deferred: %s',type(exc).__name__)
        publisher.tick()
        stop.wait(1)

def acquire_lock(state_dir):
    # Linux deployment guard: a second process must not consume the same bot queue.
    import fcntl
    handle = open(state_dir / "process.lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Another Gongsi process is already running") from None
    return handle

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    key = os.environ.get("DART_API_KEY", "").strip()
    owner = int(os.environ.get("TELEGRAM_OWNER_ID", "6766930417"))
    interval = int(os.environ.get("POLL_SECONDS", "300"))
    if not token or not key or interval < 60 or owner <= 0:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN, DART_API_KEY, TELEGRAM_OWNER_ID; POLL_SECONDS >= 60")
    state_dir = Path(os.environ.get("STATE_DIR", "/var/lib/gongsi"))
    state_dir.mkdir(parents=True, exist_ok=True)
    process_lock = acquire_lock(state_dir)
    store = Store(state_dir / "store.db")
    store.set("poll_seconds", interval)
    release_file = Path("RELEASE")
    store.set("release", release_file.read_text(encoding="ascii").strip() if release_file.exists() else "local")
    tg = Telegram(token)
    identity = tg.call("getMe")
    if identity.get("username") != os.environ.get("TELEGRAM_BOT_USERNAME", "auto_dart_gongsi_bot"):
        raise RuntimeError("Unexpected bot username")
    chat = tg.call("getChat", chat_id=owner)
    if chat.get("type") != "private" or chat.get("id") != owner:
        raise RuntimeError("Owner private chat verification failed")
    if tg.call("getWebhookInfo").get("url"):
        raise RuntimeError("Existing webhook detected; remove it before using this long-polling service")
    bot = Bot(tg, store, owner)
    bot.extractor = Extractor(key, store, int(os.environ.get("DART_DAILY_LIMIT", "18000")))
    bot.register_menu()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    dart = Dart(key, store, int(os.environ.get("DART_DAILY_LIMIT", "18000")))
    thread = threading.Thread(target=worker, args=(dart, bot, store, stop, interval), daemon=True)
    thread.start()
    ready = Path(os.environ.get("READY_FILE", "/run/gongsi/ready"))
    ready.write_text(str(os.getpid()), encoding="ascii")
    LOG.info("Started; private menu ready; poll_seconds=%s", interval)
    try:
        while not stop.is_set():
            if not thread.is_alive():
                raise RuntimeError("DART worker stopped")
            offset = store.get("telegram_offset", 0)
            try:
                updates = tg.call("getUpdates", offset=offset, timeout=20, limit=100,
                                  allowed_updates=["message", "callback_query"])
                for update in updates:
                    try:
                        bot.handle(update)
                    except ApiError as exc:
                        if exc.code != "400":
                            raise
                        # Expired callbacks/deleted messages must not block all later commands.
                        LOG.warning("Skipped an expired or invalid Telegram action")
                    store.set("telegram_offset", update["update_id"] + 1)
            except ApiError as exc:
                LOG.error("Menu update failed: %s", exc)
                stop.wait(max(3, exc.retry_after))
    finally:
        stop.set()
        thread.join(timeout=45)
        ready.unlink(missing_ok=True)
        if not thread.is_alive():
            store.close()
        process_lock.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        safe = str(exc) if isinstance(exc, (ApiError, RuntimeError)) else type(exc).__name__
        LOG.error("Service stopped: %s", safe)
        raise SystemExit(1)

