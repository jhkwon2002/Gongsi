import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('gongsi_healthcheck', Path(__file__).resolve().parents[1]/'deploy/healthcheck.py')
health=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)
NOW=datetime(2026,10,26,10,40,tzinfo=timezone(timedelta(hours=9)))


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.config={'TELEGRAM_OWNER_ID':str(health.OWNER),'TELEGRAM_BOT_TOKEN':'FAKE_SECRET_TOKEN','DART_API_KEY':'FAKE_SECRET_DART'}
        self.state={'last_scan_success':NOW.isoformat(),'last_scan_error':'','poll_seconds':300,
                    'settings':{'selected':['major'],'paused':False},'release':'abc'}

    def check(self, status='000', telegram=None, send=True):
        replies=telegram if telegram is not None else [{'username':health.BOT_USERNAME},{'message_id':123}]
        with patch.object(health,'now_kst',return_value=NOW),patch.object(health,'request_json',return_value={'status':status}),patch.object(health.Telegram,'call',side_effect=replies) as call:
            result=health.run_checks(self.config,self.state,True,send)
        return result,call

    def test_full_test_sends_one_labelled_message_and_reports_health(self):
        result,call=self.check()
        self.assertTrue(result['health_ok'])
        self.assertTrue(result['monitoring_ready'])
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs['chat_id'],health.OWNER)
        self.assertIn('[테스트 알림]',call.call_args.kwargs['text'])
        self.assertNotIn('FAKE_SECRET',json.dumps(result))
        self.assertNotIn('FAKE_SECRET',call.call_args.kwargs['text'])

    def test_no_disclosures_is_a_successful_dart_probe(self):
        result,_=self.check('013')
        self.assertTrue(result['dart_api_ok'])

    def test_stale_scan_does_not_claim_full_health(self):
        self.state['last_scan_success']=(NOW-timedelta(hours=1)).isoformat()
        result,_=self.check()
        self.assertFalse(result['health_ok'])
        self.assertTrue(result['telegram_test_sent'])

    def test_empty_selection_reports_followup_without_changing_it(self):
        self.state['settings']['selected']=[]
        result,_=self.check()
        self.assertTrue(result['health_ok'])
        self.assertFalse(result['monitoring_ready'])
        self.assertEqual(self.state['settings']['selected'],[])

    def test_wrong_recipient_cannot_receive_test(self):
        self.config['TELEGRAM_OWNER_ID']='1'
        with patch.object(health.Telegram,'call') as call:
            with self.assertRaisesRegex(ValueError,'recipient'):
                health.run_checks(self.config,self.state,True,True)
            call.assert_not_called()

    def test_wrong_bot_cannot_send_test(self):
        with self.assertRaisesRegex(ValueError,'bot'):
            self.check(telegram=[{'username':'another_bot'}])

    def test_read_only_mode_sends_no_message(self):
        result,call=self.check(telegram=[{'username':health.BOT_USERNAME}],send=False)
        self.assertTrue(result['health_ok'])
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args[0],'getMe')

    def test_invalid_dart_auth_does_not_claim_healthy(self):
        result,_=self.check(status='010')
        self.assertFalse(result['dart_api_ok'])
        self.assertFalse(result['health_ok'])

    def test_state_reader_requires_an_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with self.assertRaises(sqlite3.OperationalError):
                health.read_state(path)
            self.assertFalse(path.exists())
