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

def matches(title, selected):
    name = normalize(title)
    for key in selected:
        item = BY_KEY.get(key)
        if not item:
            continue
        for term in item.terms:
            # Specific decisions appear inside 주요사항보고서(...), or as standalone titles.
            if name.startswith(term) or ("결정" in term or key == "trust") and term in name:
                return True
    return False


# Presentation groups preserve the existing persistent filter keys.
GROUPS = (('business', '경영·계약', ('investment', 'management', 'contracts', 'major')), ('financing', '자금조달·증권발행', ('capital_up', 'bonus', 'cb', 'bw', 'eb', 'conversion', 'securities', 'issue_result', 'issuance_result', 'prospectus', 'shelf', 'effective', 'small_offer')), ('assets', '자산·사업구조', ('assets', 'merger', 'merger_end', 'securitization')), ('treasury', '자기주식·주식구조', ('buyback', 'treasury_sale', 'trust', 'treasury_result', 'cancellation', 'stock_structure')), ('financial', '실적·재무보고', ('annual', 'half', 'quarter', 'audit', 'earnings', 'earnings_notice')), ('governance', '주주·지배구조', ('holdings', 'insider', 'trade_plan', 'owner_change', 'agm_notice', 'agm_result', 'record_date', 'proxy', 'options', 'directors')), ('related', '보증·관계회사 거래', ('guarantee', 'collateral', 'related_funds', 'intragroup')), ('risk', '소송·시장조치', ('litigation', 'market', 'explanation')), ('ir_value', 'IR·기업가치', ('ir', 'value_up')))
GROUP_BY_KEY = {g[0]: g for g in GROUPS}
