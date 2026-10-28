"""Explicit notification contracts for 44 APIs, 3 financial and 16 original-table types.
Only exact source labels/keys are used; missing data is never invented.
"""
import re
from decimal import Decimal

# endpoint: ordered key=display label. Units come from official labels or explicit contracts.
CONTRACTS={
'astInhtrfEtcPtbkOpt':'rp_rsn=보고사유|ast_inhtrf_prc=양수도 가액',
'dfOcr':'df_amt=부도금액|df_bnk=발생은행|dfd=최종부도일|df_rs=사유',
'bsnSp':'bsnsp_rm=대상|bsnsp_amt=관련 매출|sl_vs=매출 대비|bsnsp_rs=사유',
'ctrcvsBgrq':'apcnt=신청인|cpct=관할법원|rqd=신청일|rq_rs=사유',
'dsRsOcr':'ds_rs=사유|ds_rsd=결정일',
'piicDecsn':'nstk_ostk_cnt=신주(보통주)|nstk_estk_cnt=신주(기타주)|ic_mthn=방식|fdpp_fclt=시설자금|fdpp_bsninh=영업양수자금|fdpp_op=운영자금|fdpp_dtrp=채무상환자금|fdpp_ocsa=타법인 취득자금|fdpp_etc=기타자금',
'fricDecsn':'nstk_ostk_cnt=신주(보통주)|nstk_estk_cnt=신주(기타주)|nstk_ascnt_ps_ostk=주당 배정(보통주)|nstk_ascnt_ps_estk=주당 배정(기타주)|nstk_asstd=기준일',
'pifricDecsn':'piic_nstk_ostk_cnt=유상 신주(보통주)|piic_nstk_estk_cnt=유상 신주(기타주)|fric_nstk_ostk_cnt=무상 신주(보통주)|fric_nstk_estk_cnt=무상 신주(기타주)|fric_nstk_ascnt_ps_ostk=주당 무상배정(보통주)|fric_nstk_ascnt_ps_estk=주당 무상배정(기타주)',
'crDecsn':'crstk_ostk_cnt=감자주식(보통주)|crstk_estk_cnt=감자주식(기타주)|bfcr_cpt=감자 전 자본금|atcr_cpt=감자 후 자본금|cr_rs=사유',
'bnkMngtPcbg':'mngt_int=관리기관|mngt_pcbg_dd=개시 결정일|mngt_pd=관리기간|mngt_rs=사유',
'lwstLg':'icnm=사건|ac_ap=원고·신청인|rq_cn=청구내용|cpct=관할',
'ovLstDecsn':'lstprstk_ostk_cnt=상장예정(보통주)|lstprstk_estk_cnt=상장예정(기타주)|lstex_nt=예정시장|lstpp=목적',
'ovDlstDecsn':'dlststk_ostk_cnt=대상(보통주)|dlststk_estk_cnt=대상(기타주)|lstex_nt=거래소|dlstrq_prd=신청예정일',
'ovLst':'lststk_ostk_cnt=상장(보통주)|lststk_estk_cnt=상장(기타주)|lstex_nt=거래소|stk_cd=종목코드|lstd=상장일',
'ovDlst':'lstex_nt=거래소|tredd=거래종료일|dlst_rs=폐지사유',
'cvbdIsDecsn':'bd_fta=발행액|bd_intr_ex=표면이율|bd_intr_sf=만기이율|cv_prc=전환가액|bd_mtd=만기',
'bdwtIsDecsn':'bd_fta=발행액|ex_prc=행사가액|bd_intr_ex=표면이율|bd_intr_sf=만기이율|bd_mtd=만기',
'exbdIsDecsn':'bd_fta=발행액|extg=교환대상|ex_prc=교환가액|bd_mtd=만기',
'bnkMngtPcsp':'mngt_int=관리기관|mngt_pcsp_dd=중단일|sp_rs=사유|ft_ctp=향후대책',
'wdCocobdIsDecsn':'bd_knd=증권종류|bd_fta=발행총액|fdpp_fclt=시설자금|fdpp_op=운영자금|fdpp_dtrp=채무상환자금|fdpp_ocsa=타법인 취득자금|fdpp_etc=기타자금',
'tsstkAqDecsn':'aqpln_stk_ostk=취득예정(보통주)|aqpln_stk_estk=취득예정(기타주)|aqpln_prc_ostk=예정금액(보통주)|aqpln_prc_estk=예정금액(기타주)|aq_pp=목적|aq_mth=방법',
'tsstkDpDecsn':'dppln_stk_ostk=처분예정(보통주)|dppln_stk_estk=처분예정(기타주)|dppln_prc_ostk=예정금액(보통주)|dppln_prc_estk=예정금액(기타주)|dp_pp=목적',
'tsstkAqTrctrCnsDecsn':'ctr_prc=계약금액|ctr_cns_int=기관|ctr_pd_bgd=기간 시작|ctr_pd_edd=기간 종료|ctr_pp=목적',
'tsstkAqTrctrCcDecsn':'ctr_prc_bfcc=해지 전 계약금액|ctr_prc_atcc=해지 후 계약금액|cc_pp=해지목적',
'bsnInhDecsn':'inh_bsn=대상|inh_prc=양수가액|inh_pp=목적|inh_prd_inh_std=양수기준일',
'bsnTrfDecsn':'trf_bsn=대상|trf_prc=양도가액|trf_pp=목적|trf_prd_trf_std=양도기준일',
'tgastInhDecsn':'ast_nm=자산|inhdtl_inhprc=양수금액|inhdtl_tast_vs=자산총액 대비|inh_pp=목적',
'tgastTrfDecsn':'ast_nm=자산|trfdtl_trfprc=양도금액|trfdtl_tast_vs=자산총액 대비|trf_pp=목적',
'otcprStkInvscrInhDecsn':'iscmp_cmpnm=대상회사|inhdtl_inhprc=양수금액|inhdtl_stkcnt=양수주식|inh_pp=목적',
'otcprStkInvscrTrfDecsn':'iscmp_cmpnm=대상회사|trfdtl_trfprc=양도금액|trfdtl_stkcnt=양도주식|trf_pp=목적',
'stkrtbdInhDecsn':'bdiscmp_cmpnm=발행회사|stkrtbd_kndn=증권종류|inhdtl_inhprc=양수금액|inh_pp=목적',
'stkrtbdTrfDecsn':'bdiscmp_cmpnm=발행회사|stkrtbd_kndn=증권종류|trfdtl_trfprc=양도금액|trf_pp=목적',
'cmpMgDecsn':'mgptncmp_cmpnm=상대회사|mg_mth=합병방식|mg_pp=합병목적|mg_rt=합병비율|mgsc_mgdt=합병기일',
'cmpDvDecsn':'dv_mth=분할방식|dv_impef=분할목적|atdv_excmp_cmpnm=존속회사|dvfcmp_cmpnm=신설회사|dvfcmp_mbsn=신설사업|dv_rt=분할비율|dvdt=분할기일|atdv_excmp_atdv_lstmn_atn=존속회사 상장유지|dvfcmp_rlst_atn=신설회사 재상장신청',
'cmpDvmgDecsn':'dvmg_mth=분할합병방식|dvmg_impef=분할합병목적|dv_trfbsnprt_cn=이전사업|atdv_excmp_cmpnm=존속회사|mgptncmp_cmpnm=합병상대|dvmg_rt=분할합병비율|dvmgsc_dvmgdt=분할합병기일',
'stkExtrDecsn':'extr_sen=구분|extr_tgcmp_cmpnm=대상법인|extr_stn=형태|extr_rt=교환비율|extr_pp=목적',
'estkRs':'stksen=증권종류|stkcnt=수량|slprc=모집가액|slta=모집총액|sbd=청약기일|pymd=납입기일',
'bdRs':'bdnmn=증권종류|slta=모집총액|sbd=청약기일|pymd=납입기일|dpcrn=표시통화',
'stkdpRs':'stksen=증권종류|stkcnt=모집수량|slprc=모집가액|slta=모집총액|sbd=청약기일|pymd=납입기일',
'mgRs':'cmpnm=대상회사|stn=형태|rt_vl=비율·가액|ctrd=계약일|mgdt_etc=관련 일정',
'extrRs':'cmpnm=대상회사|stn=형태|rt_vl=비율·가액|ctrd=계약일|mgdt_etc=관련 일정',
'dvRs':'cmpnm=대상회사|stn=형태|rt_vl=비율·가액|ctrd=계약일|mgdt_etc=관련 일정',
'majorstock':'repror=보고자|stkqy=보유주식|stkrt=보유비율|stkqy_irds=주식 증감|stkrt_irds=비율 증감|report_resn=사유',
'elestock':'repror=보고자|isu_exctv_ofcps=직위|sp_stock_lmp_cnt=소유주식|sp_stock_lmp_irds_cnt=주식 증감|sp_stock_lmp_rate=소유비율',
}
CONTRACTS={k:[tuple(x.split('=')) for x in v.split('|')] for k,v in CONTRACTS.items()}

def key(s):
    return re.sub(r'[\s·ㆍ.,:()\-]','',s).replace('양수','취득').replace('양도','처분')

def number(value, unit):
    value=str(value).strip()
    m=re.fullmatch(r'([+-]?[\d,]+(?:\.\d+)?)',value)
    if not m:
        return value
    n=Decimal(m.group(1).replace(',',''))
    def fmt(n):
        return format(n,',f').rstrip('0').rstrip('.') if n%1 else format(int(n),',')
    if unit in ('원','천원','백만원','억원','KRW'):
        n*=Decimal({'원':1,'KRW':1,'천원':1000,'백만원':1000000,'억원':100000000}[unit])
        return fmt(n/100000000)+'억원' if abs(n)>=100000000 else fmt(n)+'원'
    if unit=='주' and abs(n)>=10000:
        return fmt(n/10000)+'만주'
    return ('+' if value.startswith('+') else '')+fmt(n)+unit

def unit_for(label, field=''):
    if '증감' in label and ('비율' in label or 'rate' in field):
        return '%p'
    match=re.search(r'\((원|천원|백만원|억원|%|주)\)',label.replace(' ',''))
    if match:
        return match.group(1)
    if field in ('stkqy','stkqy_irds','sp_stock_lmp_cnt','sp_stock_lmp_irds_cnt'):
        return '주'
    if field in ('stkrt','sp_stock_lmp_rate'):
        return '%'
    return ''


def has_value(value, label=''):
    """Omit explicit absence markers and zero amounts/ratios, preserving real text."""
    if value is None:
        return False
    raw=str(value).strip()
    financial=re.fullmatch(r'.+?: (.*?) \[([A-Z]{3}|통화 미확인)\]; .*',raw)
    if financial:
        raw=financial.group(1)+' ['+financial.group(2)+']'
    unit_match=re.search(r'\s*\[(?:단위\s*[:：]\s*)?(원|천원|백만원|억원|%|%p|주|명|USD|KRW)\]\s*$', raw)
    source_unit=unit_match.group(1) if unit_match else ''
    if unit_match:
        raw=raw[:unit_match.start()].strip()
    token=re.sub(r'[\s.()（）]', '', raw).casefold()
    if token in ('', '-', '‐', '–', '—', '−', '―', '해당없음', '해당사항없음',
                 '해당사항이없음', '없음', 'na', 'null', 'none'):
        return False
    zero=re.fullmatch(r'[+-]?0+(?:\.0+)?\s*(원|천원|백만원|억원|%p?|USD|KRW)?', raw.replace(',',''))
    if zero and (zero.group(1) or source_unit in ('원','천원','백만원','억원','%','%p','USD','KRW')
                 or re.search(r'금액|가액|총액|발행액|자금|자본금|비율|대비|이율|수익률|\((?:원|천원|백만원|억원|%)\)', label.replace(' ',''))):
        return False
    # Keep comparison associations; omit the row only if all named values are absent.
    parts=raw.split(' | ')
    if len(parts)>1:
        values=[re.fullmatch(r'[^:|]{1,100}:\s*(.*)', part) for part in parts]
        if all(values):
            return any(has_value(match.group(1),label) for match in values)
    return True


def compact_division(fields):
    """Seven display categories; keep separate source records and mark excerpts."""
    output=[]
    def suffix(label):
        match=re.search(r' \[.*\]$',label)
        return match.group(0) if match else ''
    groups=list(dict.fromkeys(suffix(label) for label,value in fields))
    for group in groups:
        rows={}
        for label,value in fields:
            if suffix(label)!=group:
                continue
            name=label[:-len(group)] if group else label
            value=re.sub(r'\s+',' ',str(value)).strip()
            limit=100 if name in ('분할방식','분할목적') else 80
            value=value[:limit]+'… [발췌]' if len(value)>limit else value
            rows.setdefault(name,[]).append(value)
        def joined(name):
            return ' / '.join(dict.fromkeys(rows.get(name,[])))
        for name in ('분할방식','분할목적','존속회사','신설회사','분할비율','분할기일','상장 여부'):
            if name=='신설회사':
                value=' / '.join(part for part in (joined(name),
                                  '사업: '+joined('신설사업') if joined('신설사업') else '') if part)
            elif name=='상장 여부':
                value=' / '.join(label+': '+joined(label) for label in
                                  ('존속회사 상장유지','신설회사 재상장신청') if joined(label))
            else:
                value=joined(name)
            if value:
                output.append((name+group,value))
    return output


# Exact display labels only. Amounts, ratios, dates and financial context stay intact.
NARRATIVE_LABELS=frozenset((
    '보고사유','사유','대상','방식','방법','목적','해지목적','청구내용','폐지사유',
    '향후대책','자산','교환대상','이전사업','형태','관련 일정',
    '합병방식','합병목적','분할합병방식','분할합병목적',
    '계약명','계약조건','담보재산','근거·방법','안건','결의내용','재무제표승인',
    '주요내용','목표','시험명','판결내용','거래목적',
))

def concise_fields(fields):
    """Bound narrative excerpts without interpreting or rewriting source facts."""
    output=[]
    for label,value in fields:
        bare=re.sub(r' \[(?:증권·항목|원문표)\d+\]$','',label)
        if bare in NARRATIVE_LABELS:
            value=re.sub(r'\s+',' ',str(value)).strip()
            if len(value)>100:
                value=value[:100]+'… [발췌]'
        output.append((label,value))
    return output

def present(report, summary):
    # Lazy import avoids extraction/presentation circular imports.
    from .extraction import schema_for, SCHEMAS, RAW_PROFILES
    schema=schema_for(report['report_nm'])
    fields=[(label,value) for label,value in summary.get('fields',[]) if has_value(value,label)]
    if schema and schema.get('kind')=='financial':
        # Values already contain basis, period and currency. Preserve them verbatim.
        output=[]
        for label,value in fields:
            m=re.fullmatch(r'(.+?): ([+\-]?[\d,]+(?:\.\d+)?) \[KRW\]; (.*)',str(value))
            if m:
                period,amount,note=m.groups()
                value=period+': '+number(amount,'KRW')+'; '+note
            output.append((label,value))
        return output
    spec=[]
    if schema:
        labels={f['key']:f['label'] for f in schema['fields']}
        spec=[(labels[k],name,k) for k,name in CONTRACTS[schema['endpoint']]]
    else:
        profile=next((p for p in RAW_PROFILES if any(key(t) in key(report['report_nm']) for t in p[1])),None)
        if profile:
            spec=[(alias,RAW_NAMES.get(alias,alias),'') for alias in profile[2]]
            if '임상' in report['report_nm']:
                order=('임상시험단계','대상질환','임상시험승인기관','임상시험실시국가','신청일','승인일','목표 시험대상자 수','임상시험기간','임상시험목적','임상시험방법','임상시험실시기관','임상시험명칭','제목','사실발생일','주요내용')
                spec=[(alias,RAW_NAMES.get(alias,alias),'') for alias in order]
    result=[]
    # Record groups must not collapse different securities/companies/tables.
    groups=list(dict.fromkeys(re.search(r' \[(?:항목|표)\d+\]$',l).group(0) if re.search(r' \[(?:항목|표)\d+\]$',l) else '' for l,v in fields))
    for group in groups:
        for original,name,field in spec:
            for label,value in fields:
                suffix=re.search(r' \[(?:항목|표)\d+\]$',label)
                if (suffix.group(0) if suffix else '')!=group:
                    continue
                bare=label[:suffix.start()] if suffix else label
                if key(bare)!=key(original):
                    continue
                unit=unit_for(original,field)
                # Original-table extraction appends source units. Never infer them.
                um=re.fullmatch(r'(.+?) \[(?:단위\s*[:：]\s*)?(원|천원|백만원|억원|%|주|USD|KRW)\]',str(value))
                if um:
                    value,unit=um.groups()
                numeric=bool(re.fullmatch(r'[+\-]?[\d,]+(?:\.\d+)?',str(value)))
                value=number(value,unit)
                if numeric and not unit and any(w in name for w in ('금액','가액','총액','발행액','자금','자본금')):
                    value+=' (단위 원문 확인)'
                if group and len(groups)>1:
                    name_out=name+group.replace('항목','증권·항목').replace('표','원문표')
                else:
                    name_out=name
                pair=(name_out,value)
                if pair not in result:
                    result.append(pair)
    if not spec:
        result=[(l,v) for l,v in fields if '접수번호' not in l]
    if schema and schema['endpoint']=='cmpDvDecsn':
        return compact_division(result)
    return concise_fields(result)

RAW_NAMES={'투자구분':'투자구분','투자금액':'투자금액','자기자본대비':'자기자본 대비','투자목적':'목적','시작일':'기간 시작','종료일':'기간 종료','체결계약명':'계약명','계약금액':'계약금액','매출액대비':'매출 대비','계약상대':'상대방','계약상대방':'상대방','판매공급지역':'공급지역','주요계약조건':'계약조건','현금배당':'주당배당금','1주당배당금':'주당배당금','배당금총액':'배당총액','배당기준일':'기준일','소각할주식의종류와수':'소각주식','소각예정금액':'예정금액','소각예정일':'예정일','소각할주식의취득방법':'취득방법','채무보증금액':'보증금액','채무보증기간':'기간','담보설정금액':'설정금액','담보제공재산':'담보재산','조정전가액':'조정 전','조정후가액':'조정 후','조정사유':'사유','조정근거및방법':'근거·방법','조정가액적용일':'적용일','의안주요내용':'안건','주주총회구분':'구분','주주총회일자':'개최일','주주총회일시':'개최일시','취득주식수':'취득수량','처분주식수':'처분수량','취득가액총액':'취득총액','처분가액총액':'처분총액','개최목적':'목적','주요설명회내용':'주요내용','거래수량':'예정수량','거래목적':'목적','예정거래기간':'예정기간','사건명칭':'사건명','판결결정내용':'판결내용','판결결정일자':'판결일'}
RAW_NAMES.update({'임상시험명칭':'시험명','임상시험단계':'단계','임상시험승인기관':'승인기관','임상시험실시국가':'실시국가','임상시험실시기관':'실시기관','대상질환':'대상질환','신청일':'신청일','승인일':'승인일','임상시험목적':'목적','임상시험방법':'방법','임상시험기간':'기간','목표 시험대상자 수':'목표 대상자'})
