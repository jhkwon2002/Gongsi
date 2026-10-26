"""SQLite state lives outside releases; no credentials are stored here."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reports (receipt TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (receipt TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)

    @contextmanager
    def tx(self):
        with self.lock:
            with self.db:
                yield self.db

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def reserve_dart_request(self, limit):
        from .api import ApiError, now_kst
        day = now_kst().date().isoformat()
        with self.tx() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            quota = self.get('dart_quota', {'day':day,'count':0})
            if quota['day'] != day:
                quota = {'day':day,'count':0}
            if quota['count'] >= limit:
                raise ApiError('OpenDART','local_daily_limit')
            quota['count'] += 1
            db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',('dart_quota',json.dumps(quota)))

    def settings(self):
        return self.get("settings", {"selected": [], "paused": False, "revision": 0})

    def change_settings(self, action, key=None, enabled=None, revision=None):
        with self.lock:
            prefs = self.settings()
            if revision is not None and revision != prefs["revision"]:
                return False
            if action == "set":
                selected = set(prefs["selected"])
                if enabled:
                    selected.add(key)
                else:
                    selected.discard(key)
                prefs["selected"] = sorted(selected)
            elif action == "set_group":
                from .catalog import GROUP_BY_KEY
                group_keys = set(GROUP_BY_KEY[key][2])
                selected = set(prefs['selected'])
                prefs['selected'] = sorted(selected | group_keys if enabled else selected - group_keys)
            elif action == "clear":
                prefs["selected"] = []
            elif action in ("pause", "resume"):
                prefs["paused"] = action == "pause"
            else:
                raise ValueError("Unknown settings action")
            prefs["revision"] += 1
            self.set("settings", prefs)
            return True

    def ingest(self, reports, day, matcher):
        with self.lock:
            baseline = self.get("last_scan_day") is None
            prefs = self.settings()
            with self.tx() as db:
                for report in reports:
                    data = json.dumps(report, ensure_ascii=False)
                    changed = db.execute("INSERT OR IGNORE INTO reports VALUES (?,?)",
                                         (report["rcept_no"], data)).rowcount
                    if changed and not baseline and not prefs["paused"] and matcher(report["report_nm"], prefs["selected"]):
                        db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?)", (report["rcept_no"], data))
                db.execute("INSERT OR REPLACE INTO kv VALUES ('last_scan_day',?)", (json.dumps(day),))
            return baseline

    def pending(self, limit=20):
        with self.lock:
            rows = self.db.execute("SELECT data FROM outbox ORDER BY receipt LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge(self, receipt):
        with self.tx() as db:
            db.execute("DELETE FROM outbox WHERE receipt=?", (receipt,))

    def close(self):
        with self.lock:
            self.db.close()

