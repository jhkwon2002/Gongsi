import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gongsi.storage import Store
from gongsi.runtime_reports import Publisher,GitHubError,record,send_recorded,snapshot

REPORT={'corp_name':'Public company','report_nm':'Public filing','rcept_dt':'20261026','rcept_no':'20261026000001'}

class RuntimeReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.store.set('release','a'*40)
        self.store.set('settings',{'selected':['PRIVATE_PREFERENCE'],'private':'SECRET_SENTINEL'})

    def test_confirmed_send_records_source_without_private_identifiers(self):
        class Bot:
            def send(self,*args,**kwargs): return {'message_id':123456789,'chat':{'id':6766930417}}
        summary={'source':'OpenDART 구조화 정보','fields':[('unused','SECRET_SENTINEL')]}
        send_recorded(Bot(),self.store,REPORT,summary,'SECRET_SENTINEL','notification')
        payload=snapshot(self.store)
        row=payload['delivery_history'][0]
        self.assertEqual(row['method'],'structured_api')
        self.assertEqual(row['status'],'telegram_accepted')
        for private in ('SECRET_SENTINEL','PRIVATE_PREFERENCE','6766930417','123456789'):
            self.assertNotIn(private,json.dumps(payload))

    def test_failure_never_claims_success(self):
        class Bot:
            def send(self,*args,**kwargs): raise RuntimeError('SECRET_SENTINEL')
        with self.assertRaises(RuntimeError):
            send_recorded(Bot(),self.store,REPORT,{'source':'원문 표'},'text','test_replay')
        row=snapshot(self.store)['delivery_history'][0]
        self.assertEqual(row['status'],'send_failed')
        self.assertEqual(row['method'],'original_table')
        self.assertNotIn('SECRET_SENTINEL',json.dumps(row))

    def test_historical_cache_is_not_called_confirmed_extraction(self):
        self.store.set('test_replay:old',{'reports':[REPORT],'message_ids':[12]})
        self.store.set('extract_v4:'+REPORT['rcept_no'],{'source':'원문 표'})
        row=snapshot(self.store)['historical_replays'][0]
        self.assertEqual(row['method_evidence'],'extraction_cache_only')
        self.assertEqual(row['status'],'historical_api_acknowledged')
        self.assertNotIn('message_id',row)

    def test_missing_credential_never_attempts_network(self):
        pub=Publisher(self.store,token='')
        with patch.object(pub,'request') as request:
            pub.tick()
            request.assert_not_called()
        self.assertEqual(self.store.get('github_report_status')['status'],'credential_required')

    def test_branch_created_and_results_only_written_to_runtime_branch(self):
        pub=Publisher(self.store,token='SECRET_SENTINEL')
        responses=[GitHubError(404),{'object':{'sha':'b'*40}},{},GitHubError(404),{'commit':{'sha':'c'*40}}]
        with patch.object(pub,'request',side_effect=responses) as request:
            pub.publish(snapshot(self.store))
            writes=[call for call in request.call_args_list if len(call.args)>1]
            self.assertEqual(writes[0].args[2]['ref'],'refs/heads/runtime-reports')
            self.assertEqual(writes[1].args[2]['branch'],'runtime-reports')
            self.assertNotIn('SECRET_SENTINEL',json.dumps(writes[1].args[2]))
            pub.publish(snapshot(self.store))
            self.assertEqual(request.call_count,5)
        self.assertEqual(self.store.get('github_report_status')['status'],'synced')

    def test_network_failure_preserves_ledger_and_retries(self):
        record(self.store,REPORT,{'source':'원문 표'},'telegram_accepted','notification')
        pub=Publisher(self.store,token='SECRET_SENTINEL')
        with patch.object(pub,'request',side_effect=GitHubError(403)):
            pub.tick()
        self.assertIsNone(self.store.get('github_report_digest'))
        self.assertEqual(self.store.get('github_report_status')['error_code'],'403')
        self.assertEqual(len(snapshot(self.store)['delivery_history']),1)
        self.assertGreater(pub.next_check,0)

    def test_snapshot_exports_only_recent_200(self):
        for i in range(205):
            record(self.store,{**REPORT,'rcept_no':f'20261026{i:06d}'},None,'send_failed','notification')
        rows=snapshot(self.store)['delivery_history']
        self.assertEqual(len(rows),200)
        self.assertTrue(rows[0]['receipt'].endswith('000204'))

    def test_absent_message_id_is_not_api_confirmation(self):
        class Bot:
            def send(self,*args,**kwargs): return {}
        send_recorded(Bot(),self.store,REPORT,None,'text','notification')
        self.assertEqual(snapshot(self.store)['delivery_history'][0]['status'],'send_returned_without_id')