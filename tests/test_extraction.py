import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from gongsi.extraction import (SCHEMAS,Extractor,schema_for,structured_fields,financial_fields,
                               raw_fields,document_text,format_notification)
from gongsi.storage import Store

RECEIPT='20261026000001'
REPORT={'corp_code':'00123456','corp_name':'가상회사','report_nm':'주요사항보고서(전환사채권발행결정)','rcept_dt':'20261026','rcept_no':RECEIPT}


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db')
        self.addCleanup(self.store.close)
        self.extractor=Extractor('FAKE_SECRET',self.store)

    def test_every_official_schema_routes_to_its_endpoint(self):
        self.assertEqual(len(SCHEMAS),44)
        for schema in SCHEMAS:
            title=('증권신고서('+schema['title']+')' if schema.get('kind')=='securities'
                   else '임원ㆍ주요주주특정증권등소유상황보고서' if schema.get('kind')=='insider'
                   else '주식등의대량보유상황보고서' if schema.get('kind')=='holdings'
                   else '주요사항보고서('+schema['title']+')')
            with self.subTest(title=title):
                self.assertEqual(schema_for(title)['endpoint'],schema['endpoint'])

    def test_structured_first_and_cache_without_original_fetch(self):
        payload={'status':'000','list':[{'rcept_no':RECEIPT,'bd_fta':'10,000,000,000','cv_prc':'5,000','bd_intr_ex':'0','bd_intr_sf':'2','bd_mtd':'2029-11-30'}]}
        with patch.object(self.extractor,'json',return_value=payload) as api,patch.object(self.extractor,'original') as raw:
            result=self.extractor.extract(REPORT)
            self.assertEqual(result['source'],'OpenDART 구조화 정보')
            self.assertIn('10,000,000,000',str(result['fields']))
            self.extractor.extract(REPORT)
            api.assert_called_once()
            raw.assert_not_called()

    def test_wrong_receipt_never_attaches_another_report(self):
        schema=schema_for(REPORT['report_nm'])
        self.assertEqual(structured_fields({'list':[{'rcept_no':'20261026000999','bd_fta':'999'}]},RECEIPT,schema),[])

    def test_grouped_securities_preserve_exact_receipt(self):
        schema=schema_for('증권신고서(지분증권)')
        fields=structured_fields({'group':[{'title':'모집','list':[{'rcept_no':RECEIPT,'slta':'1000000'}]}]},RECEIPT,schema)
        self.assertIn('1000000',str(fields))

    def test_missing_structured_data_falls_back_to_original_table(self):
        report={**REPORT,'report_nm':'신규시설투자등'}
        xml='<table><tr><td>투자금액</td><td>5,000</td></tr></table>'
        with patch.object(self.extractor,'json') as api,patch.object(self.extractor,'original',return_value=xml):
            result=self.extractor.extract(report)
        self.assertEqual(result['source'],'원문 표')
        api.assert_not_called()
        self.assertIn('5,000',str(result['fields']))

    def test_rowspans_preserve_parent_label_and_unit(self):
        xml='단위: 백만원<table><tr><td rowspan="2">투자내역</td><td>투자금액</td><td>5,000</td></tr><tr><td>자기자본대비</td><td>3.2%</td></tr></table>'
        fields=raw_fields(xml,['투자금액','자기자본대비'])
        self.assertEqual(len(fields),2)
        self.assertIn('백만원',fields[0][1])
        self.assertIn('3.2%',fields[1][1])

    def test_period_headers_are_not_silently_discarded(self):
        xml='<table><tr><th>구분</th><th>당기</th><th>전기</th></tr><tr><td>매출액</td><td>100</td><td>80</td></tr></table>'
        fields=raw_fields(xml,['매출액'])
        self.assertIn('당기: 100',fields[0][1])
        self.assertIn('전기: 80',fields[0][1])

    def test_original_unavailable_keeps_alert_link_and_exposes_no_secret(self):
        with patch.object(self.extractor,'json',side_effect=OSError('FAKE_SECRET')),patch.object(self.extractor,'original',side_effect=OSError('FAKE_SECRET')):
            result=self.extractor.extract(REPORT)
        message=format_notification(REPORT,result)
        self.assertIn(RECEIPT,message)
        self.assertNotIn('FAKE_SECRET',message)
        self.assertIn('추출 불가',message)

    def test_xml_entity_declarations_are_rejected(self):
        with self.assertRaises(ValueError):
            raw_fields('<!ENTITY secret SYSTEM "file:///etc/passwd">',[])

    def test_zip_selects_main_document_not_attachment(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr(RECEIPT+'.xml','<table><tr><td>주요내용</td><td>MAIN</td></tr></table>')
            archive.writestr('attachment.xml','WRONG')
        self.assertIn('MAIN',document_text(data.getvalue(),RECEIPT))

    def test_ambiguous_archive_is_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('one.xml','ONE')
            archive.writestr('two.xml','TWO')
        with self.assertRaises(ValueError):
            document_text(data.getvalue(),RECEIPT)

    def test_oversized_document_is_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr(RECEIPT+'.xml','x'*100)
        with patch('gongsi.extraction.MAX_XML',10):
            with self.assertRaises(ValueError):
                document_text(data.getvalue(),RECEIPT)

    def test_financial_rows_preserve_basis_period_currency_and_receipt(self):
        payload={'list':[{'rcept_no':RECEIPT,'account_nm':'매출액','sj_div':'IS','fs_div':'CFS','thstrm_nm':'제10기','thstrm_amount':'123','currency':'KRW'},
                         {'rcept_no':'20261026000999','account_nm':'매출액','sj_div':'IS','thstrm_amount':'999'}]}
        result=financial_fields(payload,RECEIPT)
        self.assertEqual(len(result),1)
        self.assertIn('연결',result[0][0])
        self.assertIn('제10기',result[0][1])
        self.assertIn('KRW',result[0][1])

    def test_message_utf16_budget_preserves_source_link(self):
        message=format_notification(REPORT,{'source':'원문 표','fields':[('제목','😀'*1000)]*9})
        self.assertLessEqual(len(message.encode('utf-16-le'))//2,3800)
        self.assertIn(RECEIPT,message)

    def test_quota_is_reserved_before_network(self):
        with patch('gongsi.extraction.request_json') as request:
            with self.assertRaises(Exception):
                Extractor('FAKE',self.store,0).json('majorstock',{})
            request.assert_not_called()

    def test_explicit_cell_unit_is_retained_with_numeric_amount(self):
        fields=raw_fields('<table><tr><td>투자금액(원)</td><td>5,000,000,000</td></tr></table>',['투자금액'])
        self.assertEqual(len(fields),1)
        self.assertIn('[원]',fields[0][1])
        self.assertIn('5,000,000,000',fields[0][1])

    def test_plain_td_period_headers_remain_attached(self):
        xml='<table><tr><td>구분</td><td>당해실적</td><td>전년동기실적</td></tr><tr><td>영업이익</td><td>100</td><td>50</td></tr></table>'
        fields=raw_fields(xml,['영업이익'])
        self.assertIn('당해실적: 100',fields[0][1])
        self.assertIn('전년동기실적: 50',fields[0][1])

    def test_multiple_securities_rows_keep_their_quantity_associations(self):
        schema=schema_for('증권신고서(지분증권)')
        payload={'list':[{'rcept_no':RECEIPT,'stksen':'보통주','stkcnt':'100'},
                         {'rcept_no':RECEIPT,'stksen':'우선주','stkcnt':'200'}]}
        fields=structured_fields(payload,RECEIPT,schema)
        common=[v for k,v in fields if '[항목1]' in k]
        preferred=[v for k,v in fields if '[항목2]' in k]
        self.assertEqual(common,['보통주','100'])
        self.assertEqual(preferred,['우선주','200'])

    def test_exchange_asset_title_variants_try_official_schema_first(self):
        self.assertEqual(schema_for('유형자산취득결정')['endpoint'],'tgastInhDecsn')
        self.assertEqual(schema_for('타법인주식및출자증권처분결정')['endpoint'],'otcprStkInvscrTrfDecsn')
        fields=raw_fields('<table><tr><td>양수내역</td><td>양수금액(원)</td><td>100</td></tr></table>',['취득내역(취득금액(원))'])
        self.assertEqual(len(fields),1)

    def test_asset_transaction_amount_precedes_routine_company_metadata(self):
        schema=schema_for('타법인주식및출자증권양수결정')
        row={field['key']:'가상값' for field in schema['fields']}
        row['rcept_no']=RECEIPT
        result=structured_fields({'list':[row]},RECEIPT,schema)
        self.assertTrue(any('양수금액' in label or '양수가액' in label for label,value in result))

    def test_html_notification_highlights_company_and_hides_receipt_in_link(self):
        from html.parser import HTMLParser
        class Visible(HTMLParser):
            def __init__(self):
                super().__init__(); self.parts=[]
            def handle_data(self,data):
                self.parts.append(data)
        report={**REPORT,'corp_name':'가상A & <B>'}
        message=format_notification(report,{'source':'원문 표','fields':[('접수번호',RECEIPT),('사채의 권면(전자등록)총액 (원)','A < B & C')]},html=True)
        self.assertTrue(message.startswith('🏢 <b>가상A &amp; &lt;B&gt;</b>'))
        self.assertIn('📄 원문 보기',message)
        self.assertIn('A &lt; B &amp; C',message)
        self.assertIn(RECEIPT,message)
        parser=Visible(); parser.feed(message)
        self.assertNotIn(RECEIPT,''.join(parser.parts))
        self.assertNotIn('접수번호',''.join(parser.parts))
