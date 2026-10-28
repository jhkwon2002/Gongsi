import unittest
from gongsi.concise import summarize,compact_method,short_company,short_date
from gongsi.extraction import format_notification

class ConciseTests(unittest.TestCase):
    def test_mobis_division_uses_facts_beyond_first_100_characters(self):
        report={'corp_name':'현대모비스','report_nm':'[기재정정]주요사항보고서(회사분할결정)',
                'rcept_no':'20261028000138','rcept_dt':'20261028'}
        fields=[
            ('분할방법 [표7]','(1) 상법 제530조의2 내지 530조의12 규정에 따라 '+('사업 설명 '*25)),
            ('분할의 중요영향 및 효과 [표7]','본건 분할은 단순·물적분할 방식으로 진행됩니다. 이에 따라 최대주주 소유주식 및 지분율은 변동이 없습니다.'),
            ('분할 후 존속회사(회사명) [표7]','현대모비스 주식회사'),
            ('분할설립회사(회사명) [표7]','현대모비스 램프 주식회사(가칭)'),
            ('분할설립회사(주요사업) [표7]','자동차용 램프 부품의 생산 및 공급'),
            ('분할비율 [표7]','본건 분할은 분할회사가 분할신설회사 발행주식의 100%를 배정받는 단순·물적분할 방식이므로 분할비율을 산정하지 않습니다.'),
            ('분할기일 [표7]','2027년 04월 01일'),
            ('분할 후 존속회사(분할 후 상장유지 여부) [표7]','예'),
            ('분할설립회사(재상장신청 여부) [표7]','아니오')]
        message=format_notification(report,{'source':'원문 표','fields':fields})
        self.assertIn('분할방식: 물적분할',message)
        self.assertNotIn('분할목적:',message)
        self.assertNotIn('분할비율:',message)
        self.assertIn('신설회사 지분: 존속회사 100% 보유',message)
        self.assertIn('현대모비스 램프(가칭)',message)
        self.assertIn('2027.04.01',message)
        self.assertIn('재상장 신청 없음',message)
        self.assertNotIn('비상장',message)

    def test_method_negation_condition_and_alternatives_are_not_classified(self):
        terms=('물적분할','인적분할')
        for value in ('물적분할이 아닙니다','물적분할을 검토 중입니다',
                      '물적분할 방식으로 진행하지 않습니다','물적분할 또는 인적분할',
                      '정정 전: 물적분할, 정정 후: 인적분할',
                      '물적분할 방식으로 진행하는 경우',
                      '물적분할 방식으로 진행합니다. 다만 승인을 받으면 시행합니다.',
                      '물적분할 방식으로 진행합니다. 주주총회 승인 시 시행합니다.'):
            with self.subTest(value=value):
                self.assertIsNone(compact_method(value,terms))

    def test_contradictory_division_fields_do_not_override_method(self):
        fields=[('분할방식','물적분할이 아닙니다'),
                ('분할목적','단순·물적분할 방식으로 진행됩니다.')]
        out=summarize(fields,'cmpDvDecsn')
        self.assertEqual(out[0][1],fields[0][1])

    def test_other_method_families_use_exact_affirmative_phrases(self):
        for endpoint,label,value,expected in (
            ('cmpMgDecsn','합병방식','당사가 상대회사를 흡수합병합니다.','흡수합병'),
            ('cmpDvmgDecsn','분할합병방식','흡수분할합병','흡수분할합병'),
            ('piicDecsn','방식','제3자배정증자','제3자배정증자'),
            ('tsstkAqDecsn','방법','장내매수','장내매수')):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(summarize([(label,value)],endpoint),[(label,expected)])

    def test_only_explicit_company_and_valid_date_fields_change(self):
        self.assertEqual(short_company('주식회사 현대모비스'),'현대모비스')
        self.assertEqual(short_company('현대모비스 램프 주식회사(가칭)'),'현대모비스 램프(가칭)')
        self.assertEqual(short_date('2027년 4월 1일'),'2027.04.01')
        self.assertEqual(short_date('2027년 2월 30일'),'2027년 2월 30일')
        fields=[('금액','123,456,789'),('비율','1 : 1.2937468'),
                ('기간','2027년 4월 1일 이후 조건 충족 시'),
                ('주요내용','100% 보유하지 않습니다')]
        self.assertEqual(summarize(fields),fields)

    def test_groups_cannot_borrow_division_facts(self):
        fields=[('분할방식 [원문표1]','설명만 기재'),
                ('분할방식 [원문표2]','물적분할')]
        self.assertEqual(summarize(fields,'cmpDvDecsn'),fields)

    def test_ownership_not_inferred_from_third_party_or_conditional_percent(self):
        for ratio in (
            '제3자가 분할신설회사 발행주식의 100%를 배정받으므로 분할비율을 산정하지 않습니다.',
            '분할회사가 분할신설회사 발행주식의 100%를 배정받을 예정이며 분할비율을 산정하지 않습니다.',
            '분할회사가 분할신설회사 발행주식의 100%를 배정받으며 다른 회사는 50% 보유합니다. 분할비율을 산정하지 않습니다.'):
            out=summarize([('분할방식','물적분할'),('분할비율',ratio)],'cmpDvDecsn')
            self.assertFalse(any(label=='신설회사 지분' for label,value in out))

    def test_unclear_narrative_and_legal_conditions_remain_verbatim(self):
        fields=[('판결내용','청구 일부 인용. 나머지 청구는 기각. 항소 예정'),
                ('주요내용','임상시험에서 유효성을 확인하지 못하였으며 추가 검토가 필요합니다.'),
                ('목적','운영자금 확보 및 채무상환 조건 충족 시 투자 진행')]
        self.assertEqual(summarize(fields),fields)
        self.assertEqual(summarize([('목적','본 취득의 목적은 사업 확대입니다.')]),
                         [('목적','사업 확대')])
