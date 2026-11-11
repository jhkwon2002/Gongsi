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
    def test_different_unknown_columns_are_withheld(self):
        fields=raw_fields('<table><tr><td>금액</td><td>100</td><td>100</td></tr></table>',['금액'])
        self.assertEqual(fields,[])
        self.assertEqual(fields.withheld,1)


class ShareAcquisitionFormTests(unittest.TestCase):
    """Layout of a real 타법인주식및출자증권취득결정 table (EcoPro BM, 2026-11-10)."""
    DOC='''<table>
<tr><td rowspan="3">1. 발행회사</td><td>회사명(국적)</td><td>PT ECOPRO BNSI INVESTMENT</td><td>대표이사</td><td>이승환</td></tr>
<tr><td>자본금(원)</td><td>750,000,000</td><td>회사와 관계</td><td>종속회사</td></tr>
<tr><td>발행주식총수(주)</td><td>1,000,000</td><td>주요사업</td><td>투자</td></tr>
<tr><td rowspan="4">2. 취득내역</td><td>취득주식수(주)</td><td colspan="3">836,190,337</td></tr>
<tr><td>취득금액(원)</td><td colspan="3">627,142,752,900</td></tr>
<tr><td>자기자본(원)</td><td colspan="3">2,523,963,703,795</td></tr>
<tr><td>자기자본대비(%)</td><td colspan="3">24.8</td></tr>
<tr><td rowspan="2">3. 취득후 소유주식수 및 지분비율</td><td>소유주식수(주)</td><td colspan="3">836,700,337</td></tr>
<tr><td>지분비율(%)</td><td colspan="3">99.9</td></tr>
<tr><td colspan="2">5. 취득목적</td><td colspan="3">PT BNSI 제련소 지분취득 및 주주대여금 확보 목적</td></tr>
<tr><td colspan="2">6. 취득예정일자</td><td colspan="3">2027-06-30</td></tr>
</table>'''

    def test_calculation_markers_and_paired_rows_reach_the_notification(self):
        from gongsi.extraction import schema_for
        report={'corp_name':'가상기업','report_nm':'타법인주식및출자증권취득결정','rcept_dt':'20261110','rcept_no':'20261110900843'}
        aliases=[f['label'] for f in schema_for(report['report_nm'])['fields']]
        fields=raw_fields(self.DOC,aliases)
        self.assertEqual(fields.withheld,0)
        values=dict(fields)
        self.assertEqual(values['발행회사(회사명) [표1]'],'PT ECOPRO BNSI INVESTMENT')
        self.assertEqual(values['양수내역(양수금액(원)(A)) [표1]'],'627,142,752,900 [원]')
        self.assertEqual(values['양수내역(자기자본대비(%)(A/C)) [표1]'],'24.8 [%]')
        message=format_notification(report,{'source':'원문 표','fields':fields})
        for expected in ('대상회사: PT ECOPRO BNSI INVESTMENT','양수금액: 약 6,271억원','자기자본 대비: 24.8%',
                         '양수주식: 약 8억 3,619만주','양수 후 지분율: 99.9%','양수예정일: 2027-06-30'):
            self.assertIn(expected,message)
        self.assertNotIn('이승환',message)

    def test_unknown_second_label_in_row_is_still_withheld(self):
        doc='<table><tr><td>회사명</td><td>가상회사</td><td>비고</td><td>추가값</td></tr></table>'
        fields=raw_fields(doc,['회사명'])
        self.assertEqual(len(fields),0)
        self.assertEqual(fields.withheld,1)
