import io
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from gongsi.api import ApiError, Dart, request_json
from gongsi.bot import Bot
from gongsi.catalog import CATALOG, matches
from gongsi.storage import Store
from gongsi.__main__ import deliver, scan

OWNER = 6766930417

def report(number, title="증권발행실적보고서"):
    return {"rcept_no": f"20261023{number:06d}", "report_nm": title,
            "rcept_dt": "20261023", "corp_name": "테스트"}

class Telegram:
    def __init__(self):
        self.calls = []
        self.fail = False
    def call(self, method, **body):
        if self.fail:
            raise ApiError("Telegram", 503)
        self.calls.append((method, body))
        return {"chat": {"id": OWNER}}

class NoWait:
    def is_set(self):
        return False
    def wait(self, seconds):
        return False

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "store.db"
        self.store = Store(self.path)
        self.tg = Telegram()
        self.bot = Bot(self.tg, self.store, OWNER)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def select(self, *keys):
        for key in keys:
            self.store.change_settings("set", key, True)
    def prime(self):
        self.store.ingest([report(1)], "2026-10-23", matches)
    def callback(self, data, sender=OWNER, chat=OWNER):
        return {"callback_query": {"id": "cb1", "data": data, "from": {"id": sender},
                  "message": {"message_id": 3, "chat": {"id": chat, "type": "private"}}}}

    def test_empty_selection_until_user_chooses(self):
        self.assertEqual(self.store.settings()["selected"], [])
    def test_selection_persists_on_restart(self):
        self.select("cb", "annual")
        reopened = Store(self.path)
        try:
            self.assertEqual(reopened.settings()["selected"], ["annual", "cb"])
        finally:
            reopened.close()
    def test_buttons_cover_catalog_and_fit_telegram_limit(self):
        ids = set()
        for page in range((len(CATALOG) + 5) // 6):
            _, markup = self.bot.menu(page)
            for row in markup["inline_keyboard"]:
                for button in row:
                    data = button["callback_data"]
                    self.assertLessEqual(len(data.encode()), 64)
                    if data.startswith("s:"):
                        ids.add(data.split(":")[1])
        self.assertEqual(ids, {item.key for item in CATALOG})
    def test_owner_callback_changes_preference(self):
        self.bot.handle(self.callback("s:issue_result:1:0:0"))
        self.assertEqual(self.store.settings()["selected"], ["issue_result"])
    def test_stale_callback_cannot_toggle_again(self):
        update = self.callback("s:issue_result:1:0:0")
        self.bot.handle(update)
        self.bot.handle(update)
        self.assertEqual(self.store.settings()["revision"], 1)
        self.assertEqual(self.store.settings()["selected"], ["issue_result"])
    def test_other_person_cannot_change_settings(self):
        self.bot.handle(self.callback("s:issue_result:1:0:0", sender=999))
        self.assertEqual(self.store.settings()["selected"], [])
        self.assertFalse(self.tg.calls)
    def test_other_chat_cannot_change_settings(self):
        self.bot.handle(self.callback("s:issue_result:1:0:0", chat=-100))
        self.assertEqual(self.store.settings()["selected"], [])
    def test_corrections_and_subtypes_match(self):
        self.assertTrue(matches("[기재정정]증권발행실적보고서(파생결합증권)", ["issue_result"]))
        self.assertTrue(matches("주요사항보고서(전환사채권발행결정)", ["cb"]))
        self.assertTrue(matches("임원ㆍ주요주주특정증권등소유상황보고서", ["insider"]))
        self.assertFalse(matches("주요사항보고서(교환사채권발행결정)", ["cb"]))
    def test_first_scan_never_floods_history(self):
        self.select("issue_result")
        self.assertTrue(self.store.ingest([report(1)], "2026-10-23", matches))
        self.assertEqual(self.store.pending(), [])
    def test_duplicate_and_correction_have_distinct_receipts(self):
        self.select("issue_result")
        self.prime()
        self.store.ingest([report(1), report(2), report(3, "[기재정정]증권발행실적보고서")], "2026-10-23", matches)
        self.store.ingest([report(2), report(3)], "2026-10-23", matches)
        self.assertEqual([r["rcept_no"] for r in self.store.pending()], [report(2)["rcept_no"], report(3)["rcept_no"]])
    def test_overlapping_categories_send_once(self):
        self.select("major", "cb")
        self.prime()
        self.store.ingest([report(2, "주요사항보고서(전환사채권발행결정)")], "2026-10-23", matches)
        deliver(self.bot, self.store, NoWait())
        self.assertEqual(len(self.tg.calls), 1)
        self.assertEqual(self.store.pending(), [])
    def test_failed_delivery_stays_pending_then_retries(self):
        self.select("issue_result")
        self.prime()
        self.store.ingest([report(2)], "2026-10-23", matches)
        self.tg.fail = True
        with self.assertRaises(ApiError):
            deliver(self.bot, self.store, NoWait())
        self.assertEqual(len(self.store.pending()), 1)
        self.tg.fail = False
        deliver(self.bot, self.store, NoWait())
        self.assertEqual(self.store.pending(), [])
    def test_pause_does_not_create_backlog(self):
        self.select("issue_result")
        self.prime()
        self.store.change_settings("pause")
        self.store.ingest([report(2)], "2026-10-23", matches)
        self.store.change_settings("resume")
        self.store.ingest([report(2), report(3)], "2026-10-23", matches)
        self.assertEqual([r["rcept_no"] for r in self.store.pending()], [report(3)["rcept_no"]])
    def test_deselected_pending_item_is_not_sent(self):
        self.select("issue_result")
        self.prime()
        self.store.ingest([report(2)], "2026-10-23", matches)
        self.store.change_settings("clear")
        deliver(self.bot, self.store, NoWait())
        self.assertFalse(self.tg.calls)
        self.assertEqual(self.store.pending(), [])
    def test_new_selection_does_not_replay_observed_items(self):
        self.prime()
        self.select("issue_result")
        self.store.ingest([report(1), report(2)], "2026-10-23", matches)
        self.assertEqual(len(self.store.pending()), 1)
    def test_pagination_deduplicates(self):
        dart = Dart("fake-key", self.store)
        with patch.object(dart, "page", side_effect=[
            {"total_page": 2, "list": [report(1)]},
            {"total_page": 2, "list": [report(1), report(2)]},
        ]) as call:
            found = dart.reports("20261023", "20261023")
        self.assertEqual(len(found), 2)
        self.assertEqual(call.call_count, 2)
    def test_daily_limit_stops_before_network(self):
        dart = Dart("fake-key", self.store, daily_limit=0)
        with patch("gongsi.api.request_json") as request:
            with self.assertRaises(ApiError):
                dart.page("20261023", "20261023", 1)
        request.assert_not_called()
    def test_error_never_contains_url_or_token(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("https://secret-token")):
            with self.assertRaises(ApiError) as caught:
                request_json("Telegram", "https://api.telegram.org/botsecret-token/getMe")
        self.assertNotIn("secret-token", str(caught.exception))
    def test_failed_scan_does_not_advance_watermark(self):
        self.prime()
        dart = Dart("fake-key", self.store)
        with patch.object(dart, "reports", side_effect=ApiError("OpenDART", "020")):
            with self.assertRaises(ApiError):
                scan(dart, self.store)
        self.assertEqual(self.store.get("last_scan_day"), "2026-10-23")
    def test_menu_registration_targets_private_chat(self):
        self.bot.register_menu()
        self.assertEqual(self.tg.calls[0][1]["scope"], {"type": "chat", "chat_id": OWNER})
        self.assertEqual(self.tg.calls[1][1]["menu_button"], {"type": "commands"})
    def test_status_can_render_without_scan(self):
        self.assertIn("300", self.bot.status())


    def test_noop_menu_edit_is_harmless(self):
        with patch.object(self.tg, "call", side_effect=ApiError("Telegram", "message_not_modified")):
            self.bot.show_menu(message_id=3)

    def test_http_429_keeps_retry_after_without_exposing_body(self):
        body = io.BytesIO(b'{"parameters":{"retry_after":17},"description":"sensitive"}')
        error = urllib.error.HTTPError("https://secret-token", 429, "x", {}, body)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ApiError) as caught:
                request_json("Telegram", "https://secret-token")
        self.assertEqual(caught.exception.retry_after, 17)
        self.assertNotIn("sensitive", str(caught.exception))

if __name__ == "__main__":
    unittest.main()

