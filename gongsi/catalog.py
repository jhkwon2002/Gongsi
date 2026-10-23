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
    ReportType("assets", "중요 자산 양수·양도", ("유형자산양수결정", "유형자산양도결정", "타법인주식및출자증권양수결정", "타법인주식및출자증권양도결정", "영업양수결정", "영업양도결정")),
    ReportType("annual", "사업보고서", ("사업보고서",)),
    ReportType("half", "반기보고서", ("반기보고서",)),
    ReportType("quarter", "분기보고서", ("분기보고서",)),
    ReportType("holdings", "주식 대량보유 보고", ("주식등의대량보유상황보고서",)),
    ReportType("insider", "임원·주요주주 보유 보고", ("임원주요주주특정증권등소유상황보고서",)),
    ReportType("audit", "감사·검토 보고서", ("감사보고서", "연결감사보고서", "반기검토보고서", "반기연결검토보고서")),
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

