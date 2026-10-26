import unittest
from gongsi.extraction import SCHEMAS,RAW_PROFILES,structured_fields,raw_fields,financial_fields,format_notification
from gongsi.presentation import CONTRACTS,present,number

REPORT={'corp_name':'가상기업 & <검증>','corp_code':'00000001','rcept_no':'20261026000001','rcept_dt':'20261026'}

def cases():
    for s in SCHEMAS:
        title=('증권신고서('+s['title']+')' if s.get('kind')=='securities' else '임원ㆍ주요주주특정증권등소유상황보고서' if s.get('kind')=='insider' else '주식등의대량보유상황보고서' if s.get('kind')=='holdings' else '주요사항보고서('+s['title']+')')
        row={'rcept_no':REPORT['rcept_no'],**{k:'확인값 '+str(i) for i,(k,n) in enumerate(CONTRACTS[s['endpoint']])}}
        fields=structured_fields({'list':[row]},REPORT['rcept_no'],s)
        yield {**REPORT,'report_nm':title},{'source':'OpenDART 구조화 자료','fields':fields},[n for k,n in CONTRACTS[s['endpoint']]]
    for title in ('사업보고서','반기보고서','분기보고서'):
        fields=financial_fields({'list':[{'rcept_no':REPORT['rcept_no'],'account_nm':'매출액','sj_div':'IS','fs_div':'CFS','thstrm_nm':'당기 누적','currency':'KRW','thstrm_amount':'10000000000'}]},REPORT['rcept_no'])
        yield {**REPORT,'report_nm':title+' (2026.09)'},{'source':'OpenDART 구조화 자료','fields':fields},None
    for title,terms,aliases in RAW_PROFILES:
        body='<table>'+''.join('<tr><td>'+a+'</td><td>원문값 '+str(i)+'</td></tr>' for i,a in enumerate(aliases))+'</table>'
        yield {**REPORT,'report_nm':terms[0]},{'source':'원문 표','fields':raw_fields(body,aliases)},None

class PresentationTests(unittest.TestCase):
    def test_all_63_contracts_reach_actual_notification_formatter(self):
        all_cases=list(cases())
        self.assertEqual(len(all_cases),63)
        self.assertEqual(len(CONTRACTS),44)
        for report,summary,expected in all_cases:
            with self.subTest(title=report['report_nm']):
                fields=present(report,summary)
                self.assertTrue(fields)
                if expected:
                    self.assertEqual([l for l,v in fields],expected)
                message=format_notification(report,summary,html=True)
                self.assertIn('가상기업 &amp; &lt;검증&gt;',message)
                self.assertNotIn('핵심 항목을 확보하지 못',message)
                self.assertIn('원문 보기',message)
                self.assertLessEqual(len(message.encode('utf-16-le'))//2,3800)
    def test_only_explicit_units_converted(self):
        self.assertEqual(number('10000000000','원'),'100억원')
        self.assertEqual(number('123450000','원'),'1.2345억원')
        self.assertEqual(number('1000000','주'),'100만주')
        self.assertEqual(number('10000000000','USD'),'10,000,000,000USD')
        self.assertEqual(number('500','백만원'),'5억원')
        self.assertEqual(number('+1.0','%p'),'+1%p')
        self.assertEqual(number('2026-11-30',''),'2026-11-30')
    def test_two_securities_keep_each_amount_with_its_kind(self):
        s=next(s for s in SCHEMAS if s['endpoint']=='estkRs')
        rows=[{'rcept_no':REPORT['rcept_no'],'stksen':k,'slta':a} for k,a in [('보통주','100'),('우선주','200')]]
        fields=structured_fields({'list':rows},REPORT['rcept_no'],s)
        out=present({**REPORT,'report_nm':'증권신고서(지분증권)'},{'fields':fields})
        self.assertEqual(len(out),4)
        self.assertIn('보통주',out[0][1]);self.assertIn('100',out[1][1])
        self.assertIn('우선주',out[2][1]);self.assertIn('200',out[3][1])
    def test_missing_fields_not_filled_from_unrelated_rows(self):
        report={**REPORT,'report_nm':'주요사항보고서(전환사채권 발행결정)'}
        message=format_notification(report,{'source':'원문 표','fields':[('무관한항목','999')]})
        self.assertIn('핵심 항목을 확보하지 못',message)
        self.assertNotIn('999',message)
    def test_financial_basis_period_currency_survive(self):
        report,summary,_=list(cases())[44]
        value=present(report,summary)[0]
        self.assertIn('연결',value[0]);self.assertIn('누적',value[1]);self.assertIn('100억원',value[1])