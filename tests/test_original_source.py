import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from gongsi.original_source import (OriginalSourceError, original_fields, viewer_params, read_html)
from gongsi.extraction import Extractor, document_text, format_notification
from gongsi.storage import Store

RECEIPT='20261027800235'
REPORT={'rcept_no':RECEIPT,'corp_code':'00000001','corp_name':'가상회사',
        'rcept_dt':'20261027','report_nm':'신규시설투자등'}
TABLE='''<table>
<tr><td rowspan="2">2. 투자내역</td><td>투자금액(원)</td><td>100,000,000,000</td></tr>
<tr><td>자기자본대비(%)</td><td>5.25</td></tr>
<tr><td colspan="2">3. 투자목적</td><td>생산능력 확대</td></tr>
<tr><td rowspan="2">4. 투자기간</td><td>시작일</td><td>2026-10-27</td></tr>
<tr><td>종료일</td><td>2028-12-31</td></tr></table>'''


class OriginalFallbackTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'store.db')
        self.addCleanup(self.store.close)
        self.ex=Extractor('SECRET_SENTINEL',self.store)

    def test_api_archive_success_does_not_fetch_html(self):
        with patch.object(self.ex,'original',return_value=TABLE),patch('gongsi.original_source.html_document') as web:
            evidence={}
            fields=original_fields(self.ex,RECEIPT,['투자금액'],evidence)
        self.assertTrue(fields)
        web.assert_not_called()
        self.assertEqual(evidence['original_source'],'document_api')

    def test_unavailable_archive_falls_back_and_formats_facility_contract(self):
        with patch.object(self.ex,'original',side_effect=ValueError('DART original document unavailable')),patch('gongsi.original_source.html_document',return_value=TABLE) as web:
            result=self.ex.extract(REPORT)
        web.assert_called_once_with(self.ex,RECEIPT)
        self.assertEqual(result['source'],'원문 표')
        self.assertEqual(result['evidence']['original_source'],'dart_html')
        self.assertEqual(result['evidence']['original_attempts'][0]['reason'],'not_zip')
        message=format_notification(REPORT,result)
        for value in ('1,000억원','5.25%','생산능력 확대','2026-10-27','2028-12-31'):
            self.assertIn(value,message)

    def test_empty_archive_table_retries_html(self):
        with patch.object(self.ex,'original',return_value='<table></table>'),patch('gongsi.original_source.html_document',return_value=TABLE):
            result=self.ex.extract(REPORT)
        self.assertTrue(result['fields'])
        self.assertEqual(result['evidence']['original_attempts'][0]['reason'],'no_matching_fields')

    def test_bad_table_retries_html(self):
        with patch.object(self.ex,'original',return_value='<table><tr><td>금액'),patch('gongsi.original_source.html_document',return_value=TABLE):
            result=self.ex.extract(REPORT)
        self.assertEqual(result['evidence']['original_attempts'][0]['stage'],'table')
        self.assertTrue(result['fields'])

    def test_both_failures_record_stage_without_secrets(self):
        with patch.object(self.ex,'original',side_effect=ValueError('DART original document unavailable')),patch('gongsi.original_source.html_document',side_effect=OSError('SECRET_SENTINEL')):
            result=self.ex.extract(REPORT)
        self.assertFalse(result['fields'])
        self.assertEqual(len(result['evidence']['original_attempts']),2)
        self.assertNotIn('SECRET_SENTINEL',str(result))
        self.assertIsNone(self.store.get('extract_v5:'+RECEIPT))

    def test_api_partial_values_survive_failed_html(self):
        report={**REPORT,'report_nm':'주요사항보고서(회사합병결정)'}
        with patch.object(self.ex,'json',return_value={'status':'000','list':[{'rcept_no':RECEIPT,'mg_mth':'API 방식'}]}),patch.object(self.ex,'original',side_effect=ValueError('DART original document unavailable')),patch('gongsi.original_source.html_document',side_effect=OSError()):
            result=self.ex.extract(report)
        self.assertIn(('합병방법','API 방식'),result['fields'])

    def test_literal_viewer_requires_exact_receipt(self):
        page="viewDoc('20261027000000','999','0','0','0','HTML');viewDoc('%s','123','0','0','0','HTML')"%RECEIPT
        params=viewer_params(page,RECEIPT)
        self.assertEqual(params['rcpNo'],RECEIPT)
        self.assertEqual(params['dcmNo'],'123')
        with self.assertRaises(OriginalSourceError):
            viewer_params(page,'20261027000999')

    def test_document_ids_are_never_guessed_or_mixed(self):
        page="viewDoc('%s','123','0','0','0','HTML');viewDoc('%s','456','0','0','0','HTML')"%(RECEIPT,RECEIPT)
        with self.assertRaises(OriginalSourceError):
            viewer_params(page,RECEIPT)

    def test_tree_node_parameters_and_xsd_names(self):
        data={'rcpNo':RECEIPT,'dcmNo':'123','eleId':'1','offset':'250','length':'1000','dtd':'dart3.xsd'}
        page='\n'.join("node1['%s'] = '%s';"%(k,v) for k,v in data.items())
        self.assertEqual(viewer_params(page,RECEIPT),data)

    def test_api_error_code_is_distinguished_and_quota_errors_do_not_retry(self):
        with self.assertRaises(OriginalSourceError) as error:
            document_text(b'<result><status>014</status></result>',RECEIPT)
        self.assertEqual(error.exception.reason,'api_status_014')
        with patch.object(self.ex,'original',side_effect=OriginalSourceError('document_api','api_status_020')),patch('gongsi.original_source.html_document') as web:
            self.ex.extract(REPORT)
        web.assert_not_called()

    def test_html_download_is_bounded_and_decodes_declared_encoding(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.geturl.return_value='https://dart.fss.or.kr/report/viewer.do'
        headers=Message();headers['Content-Type']='text/html; charset=euc-kr'
        response.headers=headers
        response.read.return_value=TABLE.encode('euc-kr')
        with patch('gongsi.original_source.urlopen',return_value=response):
            self.assertIn('투자목적',read_html(response.geturl()))
        response.read.return_value=b'x'*11
        with patch('gongsi.original_source.MAX_PAGE',10),patch('gongsi.original_source.urlopen',return_value=response):
            with self.assertRaises(OriginalSourceError):
                read_html(response.geturl())

    def test_read_only_probe_never_sends_or_replays(self):
        import json
        from datetime import datetime,timezone,timedelta
        from gongsi.api_diagnostics import run_original_probe,ORIGINAL_KEY
        self.store.db.execute('INSERT INTO reports VALUES (?,?)',(RECEIPT,json.dumps(REPORT)))
        self.store.db.commit()
        bot=Mock();bot.extractor=self.ex
        now=datetime(2026,10,27,14,tzinfo=timezone(timedelta(hours=9)))
        with patch.object(self.ex,'original',side_effect=ValueError('DART original document unavailable')),patch('gongsi.original_source.html_document',return_value=TABLE) as web:
            run_original_probe(bot,self.store,now)
            run_original_probe(bot,self.store,now)
        self.assertTrue(self.store.get(ORIGINAL_KEY)['complete'])
        web.assert_called_once()
        bot.send.assert_not_called()


    def test_seven_argument_current_dart_calls_are_supported(self):
        for receipt,dcm in (('20261027800573','11629144'),('20261027800571','11629225')):
            page='viewDoc("%s", "%s", "0", "0", "0", "HTML", "")'%(receipt,dcm)
            p=viewer_params(page,receipt)
            self.assertEqual(p['dcmNo'],dcm)
            self.assertEqual(p['eleId'],'0')

    def test_attachment_whole_document_beats_last_tree_section(self):
        page='viewDoc("%s", "123", "0", "0", "0", "dart4.xsd", "");'%RECEIPT
        page+="node1['rcpNo']='%s';node1['dcmNo']='123';node1['eleId']='2';node1['offset']='100';node1['length']='200';node1['dtd']='dart4.xsd';"%RECEIPT
        self.assertEqual(viewer_params(page,RECEIPT)['eleId'],'0')

    def test_reference_requires_unique_explicit_older_root(self):
        from gongsi.original_source import parent_reference
        page='<option value="rcpNo=20261026000365">본문</option><option value="rcpNo=20261026000365&amp;dcmNo=123">첨부</option>'
        with patch('gongsi.original_source.read_html',return_value=page):
            self.assertEqual(parent_reference(self.ex,'20261027000306'),'20261026000365')
        with patch('gongsi.original_source.read_html',return_value=page+'<option value="rcpNo=20261026000001">다른본문</option>'):
            self.assertIsNone(parent_reference(self.ex,'20261027000306'))
