import json
import unittest
from gongsi.storage import Store
from gongsi.runtime_reports import snapshot,requested_filing_review

RECEIPT='20261104800428'

class FilingReviewTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:')
        self.addCleanup(self.store.close)
        self.report={'rcept_no':RECEIPT,'corp_name':'현대지에프홀딩스',
                     'rcept_dt':'20261104','report_nm':'[기재정정]회사분할결정(종속회사의주요경영사항)'}
        with self.store.tx() as db:
            db.execute('INSERT INTO reports VALUES (?,?)',(RECEIPT,json.dumps(self.report)))

    def test_all_31_values_preserve_source_groups_and_leave_state_untouched(self):
        fields=[['항목'+str(i)+' [표5]','확인값 '+str(i)] for i in range(31)]
        self.store.set('extraction_evidence:'+RECEIPT,
                       {'fields':fields,'withheld':True,'evidence':{'secret':'SECRET_SENTINEL'}})
        self.store.set('prefs',{'token':'SECRET_SENTINEL'})
        before=self.store.db.execute('SELECT key,value FROM kv ORDER BY key').fetchall()
        review=snapshot(self.store)['requested_filing_review']
        self.assertEqual(review['field_count'],31)
        self.assertEqual([[x['label'],x['value']] for x in review['fields']],fields)
        self.assertTrue(review['withheld'])
        self.assertNotIn('SECRET_SENTINEL',json.dumps(review))
        self.assertEqual(before,self.store.db.execute('SELECT key,value FROM kv ORDER BY key').fetchall())
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],0)

    def test_other_company_or_receipt_is_never_exported(self):
        self.report['corp_name']='다른회사'
        with self.store.tx() as db:
            db.execute('UPDATE reports SET data=? WHERE receipt=?',(json.dumps(self.report),RECEIPT))
        self.store.set('extract_v5:'+RECEIPT,{'fields':[['회사','다른회사']]})
        result=requested_filing_review(self.store)
        self.assertEqual(result['status'],'report_identity_mismatch')
        self.assertEqual(result['fields'],[])

    def test_successful_cache_can_survive_later_failed_evidence(self):
        self.store.set('extraction_evidence:'+RECEIPT,{'fields':[]})
        self.store.set('extract_v5:'+RECEIPT,{'fields':[['분할방법 [표5]','인적분할']]})
        self.assertEqual(requested_filing_review(self.store)['fields'][0]['value'],'인적분할')

    def test_missing_or_invalid_cache_does_not_invent_values(self):
        self.assertEqual(requested_filing_review(self.store)['status'],'extraction_cache_missing')
        self.store.set('extract_v5:'+RECEIPT,{'fields':[['invalid',{'token':'SECRET_SENTINEL'}]]})
        result=requested_filing_review(self.store)
        self.assertEqual(result['status'],'invalid_cached_fields')
        self.assertEqual(result['fields'],[])
