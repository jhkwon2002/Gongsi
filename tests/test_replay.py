from datetime import datetime,timezone,timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from gongsi.storage import Store
from gongsi.test_replay import process_requests

class Stop:
    def is_set(self): return False
    def wait(self,seconds): return False

class Bot:
    owner_id=6766930417
    def __init__(self): self.calls=[]
    def send(self,message,**kwargs):
        self.calls.append((message,kwargs))
        return {'message_id':len(self.calls)}

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.bot=Bot();self.request=[{'id':'test-one','date':'2026-10-26','count':5}]
        self.store.change_settings('set','investment',True)
        for index in range(7):
            report={'rcept_no':f'20261026{index:06d}','corp_name':f'가상{index}','corp_code':str(index),'report_nm':'투자판단관련주요경영사항','rcept_dt':'20261026'}
            self.store.db.execute('INSERT INTO reports VALUES (?,?)',(report['rcept_no'],__import__('json').dumps(report)))
        self.store.db.commit()
        self.clock=patch('gongsi.test_replay.now_kst',return_value=datetime(2026,10,26,15,tzinfo=timezone(timedelta(hours=9))));self.clock.start();self.addCleanup(self.clock.stop)

    def test_five_labelled_messages_and_no_replay_on_restart(self):
        before=self.store.settings()
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),5)
        self.assertTrue(all('[테스트 재전송' in text and kwargs['parse_mode']=='HTML' for text,kwargs in self.bot.calls))
        self.assertEqual(self.store.settings(),before)
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),5)
        self.assertEqual(self.store.get('test_replay_last')['status'],'completed')

    def test_expired_request_does_not_send(self):
        self.request[0]['date']='2026-10-25'
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertFalse(self.bot.calls)

    def test_unselected_reports_do_not_send(self):
        self.store.change_settings('clear')
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertFalse(self.bot.calls)

    def test_request_cannot_exceed_ten_or_use_another_owner(self):
        self.request[0]['count']=11
        process_requests(self.bot,self.store,Stop(),self.request)
        self.request[0]['count']=5;self.bot.owner_id=1
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertFalse(self.bot.calls)

    def test_named_company_replay_is_exact_and_explicit_even_if_unselected(self):
        self.store.change_settings('clear')
        self.request[0].update(company='가상3',count=1)
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),1)
        self.assertIn('가상3',self.bot.calls[0][0])
        self.assertNotIn('가상6',self.bot.calls[0][0])
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),1)

    def test_unknown_or_invalid_company_cannot_send_other_companies(self):
        for target in ('없는기업','',[],42):
            self.request[0]['company']=target
            process_requests(self.bot,self.store,Stop(),self.request)
        self.assertFalse(self.bot.calls)

    def test_ten_reports_allow_same_company_and_checkpoint_completion(self):
        import json
        for index in range(7,12):
            report={'rcept_no':f'20261026{index:06d}','corp_name':'Same company','corp_code':'same','report_nm':'투자판단관련주요경영사항','rcept_dt':'20261026'}
            self.store.db.execute('INSERT INTO reports VALUES (?,?)',(report['rcept_no'],json.dumps(report)))
        self.store.db.commit()
        self.request[0].update(count=10,distinct_companies=False)
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),10)
        self.assertIn('Same company',self.bot.calls[0][0])
        self.assertIn('Same company',self.bot.calls[4][0])
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),10)
        self.assertEqual(self.store.get('test_replay_last')['sent'],10)

    def test_exact_receipt_cannot_select_another_company_report(self):
        self.request[0].update(company='가상3',count=1,receipt='20261026000003')
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),1)
        self.assertEqual(self.store.get('test_replay:test-one')['reports'][0]['rcept_no'],'20261026000003')
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertEqual(len(self.bot.calls),1)

    def test_receipt_and_company_mismatch_sends_nothing(self):
        self.request[0].update(company='가상3',count=1,receipt='20261026000006')
        process_requests(self.bot,self.store,Stop(),self.request)
        self.assertFalse(self.bot.calls)
