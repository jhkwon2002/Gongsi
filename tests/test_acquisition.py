import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gongsi.storage import Store
from gongsi.extraction import Extractor,SCHEMAS
from gongsi.presentation import CONTRACTS
from gongsi.acquisition import supplement

R={'rcept_no':'20261026000318','rcept_dt':'20261026','corp_code':'00000001','corp_name':'검증기업','report_nm':'주요사항보고서(회사합병결정)'}

class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.ex=Extractor('SECRET_SENTINEL',self.store)
    def test_every_44_api_contract_uses_api_without_raw_when_complete(self):
        for schema in SCHEMAS:
            title=('증권신고서('+schema['title']+')' if schema.get('kind')=='securities' else '임원ㆍ주요주주특정증권등소유상황보고서' if schema.get('kind')=='insider' else '주식등의대량보유상황보고서' if schema.get('kind')=='holdings' else '주요사항보고서('+schema['title']+')')
            receipt='20261026'+str(SCHEMAS.index(schema)).zfill(6)
            row={'rcept_no':receipt,**{k:'확인값' for k,n in CONTRACTS[schema['endpoint']]}}
            with self.subTest(endpoint=schema['endpoint']),patch.object(self.ex,'json',return_value={'status':'000','list':[row]}),patch.object(self.ex,'original') as original:
                result=self.ex.extract({**R,'report_nm':title,'rcept_no':receipt})
                self.assertEqual(result['source'],'OpenDART 구조화 정보')
                self.assertTrue(result['fields'])
                original.assert_not_called()
                self.assertEqual(result['evidence']['reason'],'api_fields_available')
    def test_api_partial_values_survive_and_only_missing_fields_supplement(self):
        payload={'status':'000','list':[{'rcept_no':R['rcept_no'],'mg_mth':'API 방식'}]}
        doc='<table><tr><td>합병방법</td><td>다른 원문 방식</td></tr><tr><td>합병상대회사</td><td>회사명</td><td>상대B</td></tr><tr><td>합병비율</td><td>1:0.5</td></tr><tr><td>합병목적</td><td>효율화</td></tr></table>'
        with patch.object(self.ex,'json',return_value=payload),patch.object(self.ex,'original',return_value=doc):
            result=self.ex.extract(R)
        self.assertIn(('합병방법','API 방식'),result['fields'])
        self.assertNotIn('다른 원문 방식',str(result['fields']))
        self.assertEqual(result['source'],'OpenDART 구조화 정보 + 원문 표 보완')
        self.assertTrue(any(p['source']=='original_table' for p in result['field_sources']))
    def test_original_failure_never_erases_api_fields(self):
        with patch.object(self.ex,'json',return_value={'status':'000','list':[{'rcept_no':R['rcept_no'],'mg_mth':'API 방식'}]}),patch.object(self.ex,'original',side_effect=RuntimeError('SECRET_SENTINEL')):
            result=self.ex.extract(R)
        self.assertIn(('합병방법','API 방식'),result['fields'])
        self.assertNotIn('SECRET_SENTINEL',str(result))
        self.assertEqual(result['evidence']['original_error'],'RuntimeError')
    def test_no_data_reason_survives_failed_original_and_is_not_cached(self):
        with patch.object(self.ex,'json',return_value={'status':'013'}),patch.object(self.ex,'original',side_effect=RuntimeError()):
            result=self.ex.extract(R)
        self.assertEqual(len(result['evidence']['attempts']),2)
        self.assertEqual(result['evidence']['reason'],'no_data')
        self.assertIsNone(self.store.get('extract_v5:'+R['rcept_no']))
        self.assertEqual(self.store.get('extraction_evidence:'+R['rcept_no'])['evidence']['reason'],'no_data')
    def test_wrong_receipt_never_becomes_api_fields(self):
        with patch.object(self.ex,'json',return_value={'status':'000','list':[{'rcept_no':'20261026000000','mg_mth':'WRONG'}]}),patch.object(self.ex,'original',side_effect=RuntimeError()):
            result=self.ex.extract(R)
        self.assertFalse(result['fields'])
        self.assertEqual(result['evidence']['reason'],'receipt_not_returned')
    def test_conflicting_raw_candidates_are_withheld(self):
        result,added,withheld=supplement([('합병방법','흡수합병')],[('합병비율 [표1]','1:0.5'),('합병비율 [표2]','1:0.6')])
        self.assertFalse(added);self.assertEqual(withheld,1)
        self.assertEqual(result,[('합병방법','흡수합병')])
    def test_multiple_api_records_are_not_mixed_with_raw_table(self):
        api=[('증권의종류 [항목1]','보통주'),('증권의종류 [항목2]','우선주')]
        result,added,_=supplement(api,[('증권수량 [표1]','100')])
        self.assertEqual(result,api);self.assertFalse(added)