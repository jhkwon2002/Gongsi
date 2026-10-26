import random
import unittest
from gongsi.extraction import raw_fields,format_notification

class ExtractionGuardTests(unittest.TestCase):
    def test_multi_level_headers_preserve_year_and_quarter(self):
        doc='<table><tr><th rowspan="2">구분</th><th colspan="2">2026년</th></tr><tr><th>1분기</th><th>2분기</th></tr><tr><td>매출액</td><td>100</td><td>80</td></tr></table>'
        fields=raw_fields(doc,['매출액'])
        self.assertIn('2026년 / 1분기: 100',fields[0][1])
        self.assertIn('2026년 / 2분기: 80',fields[0][1])
    def test_nested_table_cannot_attach_inner_value_to_outer_label(self):
        doc='<table><tr><td>투자금액</td><td><table><tr><td>매출액</td><td>999</td></tr></table></td></tr></table>'
        fields=raw_fields(doc,['투자금액','매출액'])
        self.assertTrue(fields.withheld)
        self.assertFalse(any('투자금액' in l for l,v in fields))
        self.assertEqual(fields[0][1],'999')
    def test_unit_does_not_bleed_to_next_table(self):
        fields=raw_fields('단위: 백만원<table><tr><td>투자금액</td><td>5</td></tr></table><table><tr><td>투자금액</td><td>10</td></tr></table>',['투자금액'])
        self.assertIn('백만원',fields[0][1])
        self.assertEqual(fields[1][1],'10')
    def test_global_money_unit_does_not_attach_to_percentage(self):
        fields=raw_fields('단위: 백만원<table><tr><td>자기자본대비</td><td>5%</td></tr></table>',['자기자본대비'])
        self.assertEqual(fields[0][1],'5%')
    def test_malformed_or_extreme_spans_are_withheld(self):
        for span in ('0','-1','51','999999999','n/a'):
            with self.subTest(span=span):
                fields=raw_fields('<table><tr><td>금액</td><td colspan="'+span+'">100</td></tr></table>',['금액'])
                self.assertEqual(fields,[])
                self.assertTrue(fields.withheld)
    def test_unclosed_table_rejected(self):
        with self.assertRaises(ValueError):
            raw_fields('<table><tr><td>금액</td><td>999',['금액'])
    def test_malformed_cells_are_withheld(self):
        self.assertEqual(raw_fields('<table><tr><td>금액<td>999</td></tr></table>',['금액']),[])
    def test_row_header_th_is_data_not_column_heading(self):
        fields=raw_fields('<table><tr><th>금액</th><td>100</td></tr></table>',['금액'])
        self.assertEqual(fields[0][1],'100')
    def test_duplicate_heading_names_are_ambiguous(self):
        fields=raw_fields('<table><tr><th>구분</th><th>당기</th><th>당기</th></tr><tr><td>금액</td><td>100</td><td>200</td></tr></table>',['금액'])
        self.assertEqual(fields,[])
        self.assertTrue(fields.withheld)
    def test_withheld_notice_in_real_notification(self):
        report={'corp_name':'검증기업','report_nm':'기타경영사항','rcept_dt':'20261026','rcept_no':'20261026000001'}
        message=format_notification(report,{'source':'원문 표','fields':[('제목','확인 내용')],'withheld':1})
        self.assertIn('추출을 보류',message)
        self.assertIn('확인 내용',message)
    def test_300_generated_merged_cell_layouts(self):
        rng=random.Random(20261026)
        for case in range(300):
            rows=rng.randint(1,7)
            aliases=['검증항목'+chr(65+i) for i in range(rows)]
            values=['값'+str(case)+'-'+str(i) for i in range(rows)]
            doc='<table>'+''.join('<tr><td colspan="'+str(rng.randint(1,8))+'">'+a+'</td><td colspan="'+str(rng.randint(1,8))+'">'+v+'</td></tr>' for a,v in zip(aliases,values))+'</table>'
            fields=raw_fields(doc,aliases)
            self.assertEqual([v for l,v in fields],values)
            self.assertFalse(fields.withheld)