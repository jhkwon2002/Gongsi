import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock,patch
from gongsi.storage import Store
from gongsi.api_diagnostics import run_probe,KEY,TARGETS
from gongsi.runtime_reports import snapshot

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.bot=Mock()
        for i,receipt in enumerate(TARGETS):
            r={'rcept_no':receipt,'corp_name':'Public '+str(i),'corp_code':'00000001','report_nm':'타법인주식및출자증권취득결정','rcept_dt':'20261026'}
            self.store.db.execute('INSERT INTO reports VALUES (?,?)',(receipt,json.dumps(r)))
        self.store.db.commit()
        clock=patch('gongsi.api_diagnostics.now_kst',return_value=datetime(2026,10,26,17,tzinfo=timezone(timedelta(hours=9))))
        clock.start();self.addCleanup(clock.stop)

    def test_no_data_records_four_exact_queries_and_no_telegram(self):
        self.bot.extractor.json.return_value={'status':'013','message':'SECRET_SENTINEL'}
        run_probe(self.bot,self.store)
        out=self.store.get(KEY)
        self.assertTrue(out['complete'])
        self.assertEqual(self.bot.extractor.json.call_count,4)
        self.bot.send.assert_not_called()
        self.assertTrue(all(q['reason']=='no_data' for r in out['results'] for q in r['queries']))
        self.assertNotIn('SECRET_SENTINEL',json.dumps(snapshot(self.store)))
        run_probe(self.bot,self.store)
        self.assertEqual(self.bot.extractor.json.call_count,4)

    def test_receipt_mismatch_distinguished_from_match_and_fields(self):
        self.bot.extractor.json.side_effect=[{'status':'000','list':[{'rcept_no':'20261026000000','inh_pp':'Other'}]},
             {'status':'000','list':[{'rcept_no':TARGETS[0],'inh_pp':'Matching'}]}, {'status':'013'},{'status':'013'}]
        run_probe(self.bot,self.store)
        q=self.store.get(KEY)['results'][0]['queries']
        self.assertEqual(q[0]['reason'],'receipt_not_returned')
        self.assertEqual(q[1]['reason'],'structured_fields_available')
        self.assertEqual(q[1]['extracted_field_count'],1)

    def test_failure_is_redacted_and_immediate_retry_prevented(self):
        self.bot.extractor.json.side_effect=RuntimeError('SECRET_SENTINEL')
        run_probe(self.bot,self.store)
        out=self.store.get(KEY)
        self.assertFalse(out['complete'])
        self.assertNotIn('SECRET_SENTINEL',json.dumps(out))
        run_probe(self.bot,self.store)
        self.assertEqual(self.bot.extractor.json.call_count,4)