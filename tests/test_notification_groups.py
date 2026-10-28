import unittest
from gongsi.extraction import SCHEMAS,structured_fields,format_notification
from gongsi.presentation import notification_groups,present

REPORT={'corp_name':'검증회사','report_nm':'증권신고서(지분증권)',
        'rcept_no':'20261028000138','rcept_dt':'20261028'}

class NotificationGroupTests(unittest.TestCase):
    def securities(self,kinds):
        schema=next(s for s in SCHEMAS if s['endpoint']=='estkRs')
        rows=[{'rcept_no':REPORT['rcept_no'],'stksen':kind,'slta':str(100+index)}
              for index,kind in enumerate(kinds)]
        return {'source':'OpenDART 구조화 자료',
                'fields':structured_fields({'list':rows},REPORT['rcept_no'],schema)}

    def test_internal_labels_stay_in_data_but_not_messages(self):
        summary=self.securities(('보통주','우선주'))
        original=list(summary['fields'])
        self.assertTrue(any('[증권·항목' in label for label,value in present(REPORT,summary)))
        for html in (False,True):
            message=format_notification(REPORT,summary,html=html)
            self.assertNotIn('[증권·항목',message)
            self.assertNotIn('[원문표',message)
            self.assertLess(message.index('보통주'),message.index('모집총액: 100'))
            self.assertLess(message.index('모집총액: 100'),message.index('우선주'))
            self.assertLess(message.index('우선주'),message.index('모집총액: 101'))
        self.assertEqual(summary['fields'],original)

    def test_single_group_needs_no_extra_heading(self):
        out=notification_groups([('계약금액 [원문표1]','100억원')])
        self.assertEqual(out,[(None,[('계약금액','100억원')])])

    def test_unnamed_and_duplicate_groups_are_not_merged(self):
        out=notification_groups([('금액 [원문표1]','100억원'),('금액 [원문표2]','200억원')])
        self.assertEqual([title for title,rows in out],['별도 항목 1','별도 항목 2'])
        summary=self.securities(('보통주','보통주'))
        message=format_notification(REPORT,summary)
        self.assertIn('보통주 (구분 1)',message)
        self.assertIn('보통주 (구분 2)',message)
        self.assertIn('모집총액: 100',message);self.assertIn('모집총액: 101',message)

    def test_company_and_security_names_are_escaped(self):
        summary=self.securities(('<보통주 & 특별>','우선주'))
        message=format_notification(REPORT,summary,html=True)
        self.assertIn('<b>&lt;보통주 &amp; 특별&gt;</b>',message)
        self.assertNotIn('<b><보통주',message)
        out=notification_groups([('대상회사 [원문표1]','기업A'),
                                 ('증권종류 [원문표1]','전환사채'),
                                 ('대상회사 [원문표2]','기업B')])
        self.assertEqual(out[0][0],'기업A · 전환사채')
        self.assertEqual(out[1][0],'기업B')

    def test_unknown_profile_source_markers_hidden_without_merging(self):
        report={**REPORT,'report_nm':'지원 외 보고서'}
        summary={'source':'원문 표','fields':[
            ('공개항목 [표1]','A'),('공개항목 [표2]','B')]}
        message=format_notification(report,summary)
        self.assertNotIn('[표',message)
        self.assertIn('별도 항목 1',message);self.assertIn('별도 항목 2',message)
        self.assertIn('공개항목: A',message);self.assertIn('공개항목: B',message)

    def test_ambiguous_or_excerpted_identity_is_not_used_as_heading(self):
        out=notification_groups([
            ('대상회사 [원문표1]','A'),('대상회사 [원문표1]','B'),
            ('대상회사 [원문표2]','C… [발췌]')])
        self.assertEqual([title for title,rows in out],['별도 항목 1','별도 항목 2'])

    def test_size_limit_never_leaves_orphan_heading(self):
        report={**REPORT,'report_nm':'지원 외 보고서'}
        fields=[]
        for index in range(1,35):
            fields.extend([('대상회사 [표'+str(index)+']','기업'+str(index)),
                           ('설명 [표'+str(index)+']','설명'*150)])
        message=format_notification(report,{'source':'원문 표','fields':fields},html=True)
        self.assertLessEqual(len(message.encode('utf-16-le'))//2,3800)
        self.assertIn('원문 보기',message)
        lines=message.splitlines()
        for index,line in enumerate(lines):
            if line.startswith('<b>'):
                self.assertTrue(lines[index+1].startswith('• '))
