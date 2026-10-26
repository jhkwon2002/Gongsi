import unittest
from gongsi.extraction import raw_fields,format_notification,RAW_PROFILES

class TableRegressionTests(unittest.TestCase):
    def test_clinical_rowspan_parent_yields_named_child_fields(self):
        profile=next(p for p in RAW_PROFILES if p[0]=='투자판단·기타경영사항')
        doc='''<table><tr><td rowspan="4">주요내용</td><td>2) 임상시험단계</td><td>임상 2상</td></tr>
<tr><td>3) 임상시험승인기관</td><td>식품의약품안전처</td></tr>
<tr><td>6) 대상질환</td><td>무릎 골관절염</td></tr>
<tr><td>11) 목표 시험대상자 수</td><td>63명 (최대 66명)</td></tr></table>'''
        fields=raw_fields(doc,profile[2])
        report={'corp_name':'가상기업','report_nm':'투자판단관련주요경영사항(임상시험계획승인신청)','rcept_dt':'20261026','rcept_no':'20261026000001'}
        message=format_notification(report,{'source':'원문 표','fields':fields})
        for expected in ('단계: 임상 2상','승인기관: 식품의약품안전처','대상질환: 무릎 골관절염','목표 대상자: 63명 (최대 66명)'):
            self.assertIn(expected,message)
        self.assertNotIn('열1:',message)
        self.assertNotIn('주요내용:',message)
    def test_merged_company_and_purpose_cells_are_not_repeated(self):
        doc='''<table><tr><td>회사명</td><td colspan="3">나이스프라퍼티 주식회사</td></tr>
<tr><td colspan="2">취득목적</td><td colspan="3">3개 법인 통합을 통한 경영 효율화</td></tr></table>'''
        fields=raw_fields(doc,['회사명','취득목적'])
        self.assertEqual(len(fields),2)
        self.assertEqual(fields[0][1],'나이스프라퍼티 주식회사')
        self.assertEqual(fields[1][1],'3개 법인 통합을 통한 경영 효율화')
    def test_distinct_periods_with_equal_values_are_preserved(self):
        doc='<table><tr><th>구분</th><th>당기</th><th>전기</th></tr><tr><td>매출액</td><td>100</td><td>100</td></tr></table>'
        fields=raw_fields(doc,['매출액'])
        self.assertIn('당기: 100',fields[0][1])
        self.assertIn('전기: 100',fields[0][1])
    def test_different_unknown_columns_not_silently_deduplicated(self):
        fields=raw_fields('<table><tr><td>금액</td><td>100</td><td>100</td></tr></table>',['금액'])
        self.assertIn('열1: 100',fields[0][1])
        self.assertIn('열2: 100',fields[0][1])