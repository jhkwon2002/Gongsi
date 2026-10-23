import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("gongsi_configure", Path(__file__).resolve().parents[1] / "deploy" / "configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)

class ConfigurationTests(unittest.TestCase):
    def test_environment_values_are_safe_single_lines(self):
        result = configure.build_environment("123456:FAKE_token", "a" * 40)
        self.assertIn("POLL_SECONDS=300\n", result)
        self.assertEqual(len(result.splitlines()), 9)

    def test_credential_newline_is_rejected(self):
        with self.assertRaises(ValueError):
            configure.build_environment("123456:FAKE\nINJECT=1", "a" * 40)

    def test_wrong_dart_length_is_rejected(self):
        with self.assertRaises(ValueError):
            configure.build_environment("123456:FAKE", "a" * 39)

    def test_other_bot_is_rejected_before_dart_call(self):
        with patch.object(configure.Telegram, "call", return_value={"username": "other_bot"}):
            with patch.object(configure, "request_json") as request:
                with self.assertRaises(ValueError):
                    configure.verify("fake-token", "fake-key")
                request.assert_not_called()

    def test_no_disclosures_is_valid_api_authentication(self):
        replies = [{"username": "auto_dart_gongsi_bot"}, {"id": configure.OWNER, "type": "private"}, {"url": ""}]
        with patch.object(configure.Telegram, "call", side_effect=replies):
            with patch.object(configure, "request_json", return_value={"status": "013"}):
                configure.verify("fake-token", "fake-key")

    def test_webhook_is_preserved_and_reported(self):
        replies = [{"username": "auto_dart_gongsi_bot"}, {"id": configure.OWNER, "type": "private"}, {"url": "https://existing.example"}]
        with patch.object(configure.Telegram, "call", side_effect=replies):
            with self.assertRaises(ValueError):
                configure.verify("fake-token", "fake-key")
