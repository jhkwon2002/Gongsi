"""Report families matched against OpenDART's report_nm, including corrections."""
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    terms: tuple[str, ...]

CATALOG = (
    ReportType("issue_result", "증권발행실적보고서", ("증권발행실적보고서",)),
    ReportType("securities", "증권신고서 전체", ("증권신고서",)),
    ReportType("major", "주요사항보고서 전체", ("주요사항보고서",)),
    ReportType("cb", "전환사채 발행결정", ("전환사채권발행결정",)),
    ReportType("bw", "신주인수권부사채 발행결정", ("신주인수권부사채권발행결정",)),
    ReportType("eb", "교환사채 발행결정", ("교환사채권발행결정",)),
    ReportType("capital_up", "유상증자 결정", ("유상증자결정", "유무상증자결정")),
    ReportType("bonus", "무상증자 결정", ("무상증자결정", "유무상증자결정")),
    ReportType("buyback", "자기주식 취득결정", ("자기주식취득결정",)),
    ReportType("treasury_sale", "자기주식 처분결정", ("자기주식처분결정",)),
    ReportType("trust", "자기주식 신탁계약 체결·해지", ("자기주식취득신탁계약",)),
    ReportType("merger", "합병·분할 결정", ("회사합병결정", "회사분할결정", "회사분할합병결정")),
    ReportType("assets", "중요 자산 양수·양도", ("유형자산양수결정", "유형자산양도결정", "유형자산취득결정", "유형자산처분결정", "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정", "타법인주식및출자증권양수결정", "타법인주식및출자증권양도결정", "영업양수결정", "영업양도결정")),
    ReportType("annual", "사업보고서", ("사업보고서",)),
    ReportType("half", "반기보고서", ("반기보고서",)),
    ReportType("quarter", "분기보고서", ("분기보고서",)),
    ReportType("holdings", "주식 대량보유 보고", ("주식등의대량보유상황보고서",)),
    ReportType("insider", "임원·주요주주 보유 보고", ("임원주요주주특정증권등소유상황보고서",)),
    ReportType("audit", "감사·검토 보고서", ("감사보고서", "연결감사보고서", "반기검토보고서", "반기연결검토보고서", "결합감사보고서", "분기검토보고서", "분기연결검토보고서")),
)
CATALOG += (
    ReportType('investment', '투자판단 관련 주요경영사항', ('투자판단관련주요경영사항',)),
    ReportType('management', '기타경영사항·자율공시', ('기타경영사항',)),
    ReportType('contracts', '판매·공급계약', ('단일판매공급계약',)),
    ReportType('conversion', '전환가액 조정·전환청구', ('전환가액의조정', '전환가액조정', '전환청구권행사')),
    ReportType('issuance_result', '증권발행결과', ('증권발행결과',)),
    ReportType('prospectus', '투자설명서', ('투자설명서', '간이투자설명서')),
    ReportType('shelf', '일괄신고서·추가서류', ('일괄신고서', '일괄신고추가서류')),
    ReportType('effective', '신고 효력발생 안내', ('효력발생안내',)),
    ReportType('small_offer', '소액공모', ('소액공모',)),
    ReportType('merger_end', '합병 등 종료보고', ('합병등종료보고서',)),
    ReportType('securitization', '자산유동화', ('자산유동화', '채권유동화', '자산양도등의등록신청서')),
    ReportType('treasury_result', '자기주식 결과보고', ('자기주식취득결과보고서', '자기주식처분결과보고서', '신탁계약에의한취득상황보고서', '신탁계약해지결과보고서')),
    ReportType('cancellation', '주식소각', ('주식소각결정',)),
    ReportType('stock_structure', '주식분할·병합', ('주식분할결정', '주식병합결정')),
    ReportType('earnings', '잠정실적·손익구조 변경', ('연결재무제표기준영업', '영업잠정실적', '영업(잠정)실적', '매출액또는손익구조')),
    ReportType('earnings_notice', '실적 발표 예고', ('결산실적공시예고',)),
    ReportType('owner_change', '최대주주 등 지분변동', ('최대주주등소유주식변동신고서', '최대주주변경')),
    ReportType('trade_plan', '임원·주요주주 거래계획', ('임원주요주주특정증권등거래계획보고서',)),
    ReportType('agm_notice', '주총 소집', ('주주총회소집결의', '주주총회소집공고', '주주총회소집보고서')),
    ReportType('agm_result', '주총 결과', ('정기주주총회결과', '임시주주총회결과')),
    ReportType('record_date', '주주명부·기준일', ('주주명부폐쇄기간또는기준일설정',)),
    ReportType('proxy', '의결권 대리행사', ('의결권대리행사',)),
    ReportType('options', '주식매수선택권', ('주식매수선택권',)),
    ReportType('directors', '이사 선임·퇴임', ('독립이사', '독립사외이사', '사외이사')),
    ReportType('guarantee', '채무보증', ('타인에대한채무보증결정',)),
    ReportType('collateral', '담보제공', ('타인에대한담보제공결정',)),
    ReportType('related_funds', '특수관계인 자금거래', ('특수관계인으로부터자금차입', '특수관계인에대한자금대여', '특수관계인과의예적금거래')),
    ReportType('intragroup', '계열회사 내부거래', ('동일인등출자계열회사', '특수관계인과의내부거래', '대규모내부거래', '기업집단현황공시')),
    ReportType('litigation', '소송', ('소송등의', '소송의', '소송제기')),
    ReportType('market', '거래정지·시장안내', ('주권매매거래정지', '기타시장안내', '상장폐지', '관리종목', '불성실공시')),
    ReportType('explanation', '풍문·보도 해명', ('풍문또는보도', '조회공시요구', '조회공시요구에대한답변')),
    ReportType('ir', '기업설명회·IR', ('기업설명회',)),
    ReportType('value_up', '기업가치 제고계획', ('기업가치제고계획',)),
)
BY_KEY = {item.key: item for item in CATALOG}

def normalize(title):
    title = re.sub(r"^(?:\s*\[[^\]]+\])+", "", title)
    return re.sub(r"[\sㆍ·]", "", title)

def matching_keys(title):
    name = normalize(title)
    return {item.key for item in CATALOG if item.key != 'unclassified'
            and any(name.startswith(term) or ('결정' in term or item.key == 'trust') and term in name for term in item.terms)}


def matches(title, selected):
    found = matching_keys(title)
    return bool(found.intersection(selected)) or ('unclassified' in selected and not found)


# Remaining title families confirmed by the complete audit snapshot.
CATALOG += (
    ReportType('f_efb4e35171', '특수관계인으로부터주식의취득', ('특수관계인으로부터주식의취득',)),
    ReportType('f_a4b5e0cec9', '특수관계인에대한출자', ('특수관계인에대한출자',)),
    ReportType('f_e08aa0c180', '특수관계인의유상증자참여', ('특수관계인의유상증자참여',)),
    ReportType('f_0abff1baf5', '대표이사변경', ('대표이사변경',)),
    ReportType('f_84707e9cf9', '특수관계인으로부터받은담보', ('특수관계인으로부터받은담보',)),
    ReportType('f_515cdf3447', '전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정', ('전환가액신주인수권행사가액교환가액의조정',)),
    ReportType('f_6c8b7ea93e', '임원ㆍ주요주주특정증권등거래계획철회보고서', ('임원주요주주특정증권등거래계획철회보고서',)),
    ReportType('facilities', '시설투자·증설', ('신규시설투자', '유형자산투자', '시설증설', '시설투자')),
    ReportType('f_53042c6e56', '공개매수신고서', ('공개매수신고서',)),
    ReportType('f_fa9d548275', '공개매수설명서', ('공개매수설명서',)),
    ReportType('f_5f87e19d5d', '상장채권관련기타주요사항', ('상장채권관련기타주요사항',)),
    ReportType('f_e636306e0e', '특수관계인에대한담보제공', ('특수관계인에대한담보제공',)),
    ReportType('f_bc252aeda4', '최대주주등의주식보유변동', ('최대주주등의주식보유변동',)),
    ReportType('f_dddc0b1e3b', '중대재해발생', ('중대재해발생',)),
    ReportType('f_120372c65f', '대표이사', ('대표이사',)),
    ReportType('f_e30cd6cc57', '투자유의안내', ('투자유의안내',)),
    ReportType('f_112a901710', '현금ㆍ현물배당결정', ('현금현물배당결정',)),
    ReportType('f_4a845d489a', '특수관계인에대한주식의처분', ('특수관계인에대한주식의처분',)),
    ReportType('f_9c65a5fcb6', '현금ㆍ현물배당을위한주주명부폐쇄', ('현금현물배당을위한주주명부폐쇄',)),
    ReportType('f_f884fd5a7a', '비유동자산취득결정', ('비유동자산취득결정',)),
    ReportType('f_0c21e2d329', '금전대여결정', ('금전대여결정',)),
    ReportType('f_cd3563584d', '본점소재지변경', ('본점소재지변경',)),
    ReportType('f_fc88ebd8bb', '종속회사등상장에관한찬성여부', ('종속회사등상장에관한찬성여부',)),
    ReportType('f_775bab76ba', '권리락', ('권리락',)),
    ReportType('f_22a796db8a', '특수관계인과의수익증권거래', ('특수관계인과의수익증권거래',)),
    ReportType('f_adca118ba5', '거래처와의거래중단', ('거래처와의거래중단',)),
    ReportType('f_7528b1b409', '파산신청기각', ('파산신청기각',)),
    ReportType('f_79775cde4c', '단기차입금증가결정', ('단기차입금증가결정',)),
    ReportType('f_5d969b99f6', '특수관계인으로부터기타유가증권매수', ('특수관계인으로부터기타유가증권매수',)),
    ReportType('f_69afc945d9', '특수관계인과의보험거래', ('특수관계인과의보험거래',)),
    ReportType('f_67557d4ca9', '전환사채', ('전환사채',)),
    ReportType('f_da49593c99', '특수관계인에대한채권매도', ('특수관계인에대한채권매도',)),
    ReportType('f_77dde2192a', '주권관련사채권의처분결정', ('주권관련사채권의처분결정',)),
    ReportType('f_c2067f850a', '소속부변경', ('소속부변경',)),
    ReportType('f_66a868d6cd', '수시공시의무관련사항', ('수시공시의무관련사항',)),
    ReportType('f_d0e574dc86', '공정거래자율준수프로그램운영현황', ('공정거래자율준수프로그램운영현황',)),
    ReportType('f_2ae8e21c1e', '특수관계인으로부터유가증권차입', ('특수관계인으로부터유가증권차입',)),
    ReportType('f_2628e62839', '회생절차개시신청', ('회생절차개시신청',)),
    ReportType('f_cedb92eb9d', '대규모기업집단현황공시[연1회공시및1/4분기용', ('대규모기업집단현황공시[연1회공시및1/4분기용',)),
    ReportType('f_a595fa0eb7', '유상증자또는주식관련사채등의발행결과', ('유상증자또는주식관련사채등의발행결과',)),
    ReportType('f_1e2694b315', '경영권변경등에관한계약체결', ('경영권변경등에관한계약체결',)),
    ReportType('f_723de6c7d1', '신주인수권행사', ('신주인수권행사',)),
    ReportType('f_a7c58f5f87', '회계처리기준위반에따른검찰고발등조치', ('회계처리기준위반에따른검찰고발등조치',)),
    ReportType('f_47093200a3', '증여결정', ('증여결정',)),
    ReportType('f_287de781b4', '타인을위한채무보증결정', ('타인을위한채무보증결정',)),
    ReportType('f_fa62417a8a', '특수관계인으로부터부동산임차', ('특수관계인으로부터부동산임차',)),
    ReportType('f_a621b9fa36', '횡령ㆍ배임혐의발생', ('횡령배임혐의발생',)),
    ReportType('f_94b202dc88', '회생절차개시결정', ('회생절차개시결정',)),
    ReportType('f_bd30b48cdb', '채무인수결정', ('채무인수결정',)),
    ReportType('f_b0fddfe0b3', '감자결정', ('감자결정',)),
    ReportType('f_0a3ff29ed6', '유상증자또는주식관련사채등의청약결과', ('유상증자또는주식관련사채등의청약결과',)),
    ReportType('f_b45da17a51', '외국지주회사의자회사편입ㆍ탈퇴', ('외국지주회사의자회사편입탈퇴',)),
    ReportType('f_0e4ef0bb69', '횡령ㆍ배임혐의진행사항', ('횡령배임혐의진행사항',)),
    ReportType('f_5819f2e4d7', '기타안내사항', ('기타안내사항',)),
    ReportType('f_2ffacf67ba', '전환주식의전환청구권행사', ('전환주식의전환청구권행사',)),
    ReportType('f_90902491d1', '특수관계인으로부터자산양수', ('특수관계인으로부터자산양수',)),
    ReportType('f_75208cc011', '특수관계인에대한자산양도', ('특수관계인에대한자산양도',)),
    ReportType('f_2e557b74eb', '특수관계인에대한부동산임대', ('특수관계인에대한부동산임대',)),
    ReportType('f_ac6be70444', '교환사채', ('교환사채',)),
    ReportType('f_c6d7575389', '특수관계인으로부터영업양수', ('특수관계인으로부터영업양수',)),
    ReportType('f_aaed130fa3', '특수관계인에대한영업양도', ('특수관계인에대한영업양도',)),
    ReportType('unclassified', '새 유형·미분류 공시', ()),
)
BY_KEY = {item.key: item for item in CATALOG}
GROUPS = (('business', '경영·계약', ('investment', 'management', 'contracts', 'major')), ('financing', '자금조달·증권발행', ('capital_up', 'bonus', 'cb', 'bw', 'eb', 'conversion', 'securities', 'issue_result', 'issuance_result', 'prospectus', 'shelf', 'effective', 'small_offer', 'f_515cdf3447', 'f_79775cde4c', 'f_67557d4ca9', 'f_77dde2192a', 'f_a595fa0eb7', 'f_723de6c7d1', 'f_0a3ff29ed6', 'f_2ffacf67ba', 'f_ac6be70444')), ('assets', '자산·사업구조', ('assets', 'merger', 'merger_end', 'securitization', 'facilities', 'f_f884fd5a7a', 'f_b45da17a51')), ('treasury', '자기주식·주식구조', ('buyback', 'treasury_sale', 'trust', 'treasury_result', 'cancellation', 'stock_structure', 'f_112a901710', 'f_9c65a5fcb6', 'f_775bab76ba', 'f_b0fddfe0b3')), ('financial', '실적·재무보고', ('annual', 'half', 'quarter', 'audit', 'earnings', 'earnings_notice')), ('governance', '주주·지배구조', ('holdings', 'insider', 'trade_plan', 'owner_change', 'agm_notice', 'agm_result', 'record_date', 'proxy', 'options', 'directors', 'f_0abff1baf5', 'f_6c8b7ea93e', 'f_53042c6e56', 'f_fa9d548275', 'f_bc252aeda4', 'f_120372c65f', 'f_1e2694b315')), ('related', '보증·관계회사 거래', ('guarantee', 'collateral', 'related_funds', 'intragroup', 'f_efb4e35171', 'f_a4b5e0cec9', 'f_e08aa0c180', 'f_84707e9cf9', 'f_e636306e0e', 'f_4a845d489a', 'f_0c21e2d329', 'f_22a796db8a', 'f_5d969b99f6', 'f_69afc945d9', 'f_da49593c99', 'f_2ae8e21c1e', 'f_cedb92eb9d', 'f_287de781b4', 'f_fa62417a8a', 'f_bd30b48cdb', 'f_90902491d1', 'f_75208cc011', 'f_2e557b74eb', 'f_c6d7575389', 'f_aaed130fa3')), ('risk', '소송·시장조치', ('litigation', 'market', 'explanation', 'f_dddc0b1e3b', 'f_7528b1b409', 'f_2628e62839', 'f_a7c58f5f87', 'f_a621b9fa36', 'f_94b202dc88', 'f_0e4ef0bb69')), ('ir_value', 'IR·기업가치', ('ir', 'value_up')), ('other', '기타·미분류', ('f_5f87e19d5d', 'f_e30cd6cc57', 'f_cd3563584d', 'f_fc88ebd8bb', 'f_adca118ba5', 'f_c2067f850a', 'f_66a868d6cd', 'f_d0e574dc86', 'f_47093200a3', 'f_5819f2e4d7', 'unclassified')))
GROUP_BY_KEY = {g[0]: g for g in GROUPS}
