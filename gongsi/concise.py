"""Conservative, field-scoped disclosure rules. No AI or network access."""
import re
from datetime import date

GROUP=re.compile(r' \[(?:증권·항목|원문표)\d+\]$')
COMPANIES=frozenset(('상대회사','존속회사','신설회사','합병상대','대상회사','대상법인','발행회사'))
DATES=frozenset(('분할기일','합병기일','분할합병기일','기간 시작','기간 종료','기준일',
                 '양수기준일','양도기준일','만기','청약기일','납입기일','계약일','결정일',
                 '신청일','승인일','상장일','예정일','적용일','판결일','사실발생일',
                 '확인일자','배당금지급예정일자','개최일'))
# Refuse interpretation of alternatives, negation, amendments or conditional plans.
RISK=re.compile(r'아니|아닌|아닙|아님|않|불가|검토|비교|예시|가정|가능|경우|조건|철회|취소|'
                r'정정\s*전|정정\s*후|변경\s*전|변경\s*후|대신')
METHODS={
    ('cmpDvDecsn','분할방식'):('물적분할','인적분할'),
    ('cmpMgDecsn','합병방식'):('흡수합병','신설합병'),
    ('cmpDvmgDecsn','분할합병방식'):('흡수분할합병','신설분할합병'),
    ('piicDecsn','방식'):('주주배정후실권주일반공모','주주배정증자','제3자배정증자','일반공모증자'),
    ('tsstkAqDecsn','방법'):('장내매수','장외매수','공개매수'),
}
METHOD_NAMES={'주주배정후실권주일반공모':'주주배정 후 실권주 일반공모'}
NARRATIVE=frozenset(('보고사유','사유','대상','방식','방법','목적','해지목적',
    '청구내용','폐지사유','향후대책','자산','교환대상','이전사업','형태','관련 일정',
    '합병방식','합병목적','분할방식','분할목적','분할합병방식','분할합병목적',
    '계약명','계약조건','담보재산','근거·방법','안건','결의내용','재무제표승인',
    '주요내용','목표','시험명','판결내용','거래목적','취득방법'))

def split_label(label):
    match=GROUP.search(label)
    return (label[:match.start()],match.group(0)) if match else (label,'')

def clean(value):
    return re.sub(r'\s+',' ',str(value)).strip()

def compact_method(value,terms):
    """Only complete affirmative forms; all competing terms must agree."""
    value=clean(value)
    squeezed=re.sub(r'[\s·ㆍ]','',value)
    if RISK.search(squeezed):
        return None
    found=[term for term in terms if term in squeezed]
    if len(found)!=1:
        return None
    term=found[0]
    # A bare official classification or an explicit affirmative predicate.
    if re.fullmatch(r'(?:단순[,\s]*)?'+re.escape(term)+r'(?:방식)?[.]?',squeezed):
        return METHOD_NAMES.get(term,term)
    predicate=r'(?:방식)?(?:으로(?:진행|추진|실시)|을(?:진행|실시|결정)|함(?:[.]|$)|합니다|한다|입니다|이므로)'
    if re.search(re.escape(term)+predicate,squeezed):
        return METHOD_NAMES.get(term,term)
    return None

def short_company(value):
    value=clean(value)
    value=re.sub(r'^(?:주식회사\s*|\(주\)\s*|㈜\s*)','',value)
    value=re.sub(r'\s*(?:주식회사|\(주\)|㈜)(?=\s*(?:\(가칭\))?$)','',value)
    return value.strip()

def short_date(value):
    value=clean(value)
    # ISO dates already have a compact, unambiguous representation.
    match=re.fullmatch(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',value)
    if not match:
        return value
    try:
        result=date(*map(int,match.groups()))
    except ValueError:
        return value
    return result.strftime('%Y.%m.%d')

def narrative(value):
    value=clean(value)
    # Strip only syntactic wrappers around the whole stated purpose.
    match=re.fullmatch(r'(?:본건|본|금번|이번)\s*(?:분할|합병|투자|계약|취득|처분|증자)'
                       r'(?:의)?\s*목적은\s*(.+?)(?:입니다|이다)\.?',value)
    if match:
        value=match.group(1)
    return value

def division_group(fields):
    """Cross-field division facts stay within the same company/table record."""
    rows={name:value for name,value in fields}
    types=set()
    for name in ('분할방식','분할목적','분할비율'):
        method=compact_method(rows.get(name,''),('물적분할','인적분할'))
        if method:
            types.add(method)
    method=next(iter(types)) if len(types)==1 else None
    # Any contradictory or conditional evidence blocks cross-field inference.
    explicit=set()
    for name in ('분할방식','분할목적','분할비율'):
        value=re.sub(r'[\s·ㆍ]','',str(rows.get(name,'')))
        explicit.update(term for term in ('물적분할','인적분할') if term in value)
    if len(explicit)>1 or any(RISK.search(re.sub(r'\s+','',str(rows.get(name,''))))
                              for name in ('분할방식','분할목적')):
        method=None
    ratio=clean(rows.get('분할비율',''))
    compact_ratio=re.sub(r'\s+','',ratio)
    no_ratio=bool(re.search(r'분할비율을?산정하지않',compact_ratio))
    ratio_risk=RISK.search(compact_ratio.replace('산정하지않습니다',''))
    no_ratio=no_ratio and not ratio_risk
    # Exact 100% allocation to the splitting company, not another shareholder.
    ownership=bool(re.search(
        r'분할회사(?:가|는).{0,100}분할신설회사.{0,50}(?:발행주식|지분).{0,20}'
        r'100%.{0,20}(?:배정받|보유|취득)',compact_ratio))
    percentages=re.findall(r'\d+(?:\.\d+)?%',compact_ratio)
    ownership=ownership and percentages==['100%'] and not re.search(
        r'않|아니|예정|조건|경우|변경|정정|가능|검토',compact_ratio.replace('산정하지않습니다',''))
    result=[]
    for name,value in fields:
        if name=='분할방식' and method:
            value=method
        elif name=='분할목적' and method:
            # This field often states mechanics/shareholder effects, not a purpose.
            mechanics=('방식' in str(value) and
                       any(word in str(value) for word in ('최대주주','소유주식','지분율')))
            actual_purpose=any(word in str(value) for word in ('목적','효율','경쟁력','전문화','가치','시너지'))
            if mechanics and not actual_purpose:
                continue
        elif name=='분할비율' and method=='물적분할' and no_ratio:
            if ownership:
                result.append(('신설회사 지분','존속회사 100% 보유'))
            # An explicit non-applicable ratio carries no numeric ratio.
            continue
        result.append((name,value))
    return result

def summarize(fields,endpoint=None):
    """Shared exact rules; unclear prose is left to the existing excerpt fallback."""
    groups=list(dict.fromkeys(split_label(label)[1] for label,value in fields))
    output=[]
    for group in groups:
        rows=[(split_label(label)[0],value) for label,value in fields if split_label(label)[1]==group]
        if endpoint=='cmpDvDecsn':
            rows=division_group(rows)
        for name,value in rows:
            if name in COMPANIES:
                value=short_company(value)
            elif name in DATES:
                value=short_date(value)
            elif name in NARRATIVE:
                terms=METHODS.get((endpoint,name))
                method=compact_method(value,terms) if terms else None
                value=method or narrative(value)
            if endpoint=='cmpDvDecsn':
                if name=='존속회사 상장유지' and clean(value) in ('예','아니오'):
                    value='상장 유지' if clean(value)=='예' else '상장 유지 안 함'
                elif name=='신설회사 재상장신청' and clean(value) in ('예','아니오'):
                    value='재상장 신청' if clean(value)=='예' else '재상장 신청 없음'
            output.append((name+group,value))
    return output
