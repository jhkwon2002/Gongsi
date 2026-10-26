"""Deterministic disclosure extraction. No language model or external Python packages."""
import io
import json
from pathlib import Path
import re
from html.parser import HTMLParser
import time
from urllib.parse import urlencode
import urllib.request
import zipfile
from .api import ApiError, request_json
from .catalog import normalize

SCHEMAS = json.loads(Path(__file__).with_name('extraction_schemas.json').read_text(encoding='utf-8'))
MAX_ZIP = 4 * 1024 * 1024
MAX_XML = 8 * 1024 * 1024
RAW_PROFILES = (
    ('시설투자·증설', ('신규시설투자','유형자산투자','시설증설'), ('투자구분','투자금액','자기자본대비','투자목적','시작일','종료일')),
    ('판매·공급계약', ('단일판매공급계약',), ('체결계약명','계약금액','매출액대비','계약상대','계약상대방','판매공급지역','시작일','종료일','주요계약조건')),
    ('잠정실적', ('잠정','매출액또는손익구조'), ('매출액','영업이익','법인세비용차감전계속사업이익','당기순이익','지배기업소유주지분순이익')),
    ('배당', ('현금현물배당','주식배당'), ('배당구분','배당종류','1주당배당금','시가배당율','배당금총액','배당기준일','배당금지급예정일자')),
    ('주식소각', ('주식소각',), ('소각할주식의종류와수','소각예정금액','소각예정일','소각할주식의취득방법')),
    ('채무보증', ('채무보증',), ('채무자','채권자','채무보증금액','자기자본대비','시작일','종료일','채무보증총잔액')),
    ('담보제공', ('담보제공',), ('채무자','채권자','담보설정금액','담보제공재산','자기자본대비','시작일','종료일')),
    ('전환·행사가액 조정', ('전환가액','행사가액','교환가액'), ('조정전가액','조정후가액','조정사유','조정근거및방법','조정가액적용일')),
    ('주총 소집', ('주주총회소집',), ('일시','장소','의안주요내용','주주총회구분')),
    ('주총 결과', ('주주총회결과',), ('재무제표승인','결의내용','주주총회일자','주주총회구분')),
    ('자기주식 결과보고', ('자기주식취득결과','자기주식처분결과','신탁계약해지결과','신탁계약에의한취득상황'), ('주식의종류','취득주식수','처분주식수','취득가액총액','처분가액총액','취득기간','처분기간','신탁계약금액')),
    ('IR 개최', ('기업설명회',), ('일시','장소','참가대상자','개최목적','주요설명회내용','후원기관')),
    ('투자판단·기타경영사항', ('투자판단관련','기타경영사항'), ('제목','주요내용','사실발생일','확인일자','결정일자')),
    ('기업가치 제고계획', ('기업가치제고',), ('제목','주요내용','계획기간','이사회결의일','목표')),
    ('임원·주요주주 거래계획', ('거래계획',), ('보고자','거래목적','거래금액','거래수량','거래기간','예정거래기간')),
    ('소송 판결·진행', ('소송',), ('사건명칭','원고신청인','청구내용','판결결정내용','관할법원','판결결정일자','확인일자')),
)
PREFERRED = {
 'piicDecsn': ('nstk_ostk_cnt','ic_mthn','fdpp_fclt','fdpp_op','fdpp_dtrp','fdpp_ocsa'),
 'fricDecsn': ('nstk_ostk_cnt','nstk_ascnt_ps_ostk','nstk_asstd','nstk_lstprd'),
 'cvbdIsDecsn': ('bd_fta','fdpp_fclt','fdpp_op','bd_intr_ex','bd_intr_sf','cv_prc','bd_mtd','cvrqpd_bgd','cvrqpd_edd'),
 'bdwtIsDecsn': ('bd_fta','bd_intr_ex','bd_intr_sf','ex_prc','bd_mtd','expd_bgd','expd_edd'),
 'exbdIsDecsn': ('bd_fta','extg','ex_prc','bd_intr_ex','bd_intr_sf','bd_mtd','exrqpd_bgd','exrqpd_edd'),
 'tsstkAqDecsn': ('aqpln_stk_ostk','aqpln_prc_ostk','aq_pp','aq_mth','aqexpd_bgd','aqexpd_edd'),
 'tsstkDpDecsn': ('dppln_stk_ostk','dppln_prc_ostk','dp_pp','dp_mth','dpexpd_bgd','dpexpd_edd'),
 'cmpMgDecsn': ('mg_mth','mg_pp','mg_rt','mgptncmp_cmpnm','mgsc_mgdt'),
 'majorstock': ('repror','stkqy','stkqy_irds','stkrt','stkrt_irds','report_resn'),
 'elestock': ('repror','isu_exctv_ofcps','sp_stock_lmp_cnt','sp_stock_lmp_irds_cnt','sp_stock_lmp_rate','sp_stock_lmp_irds_rate'),
 'estkRs': ('stksen','stkcnt','slprc','slta','slmthn','sbd','pymd'),
}


def text(value, limit=260):
    value = re.sub(r'\s+', ' ', str(value)).strip()
    return value[:limit] + ('… [발췌]' if len(value) > limit else '')


def schema_for(title):
    name = normalize(title)
    for prefix in ('사업보고서','반기보고서','분기보고서'):
        if name.startswith(prefix):
            return {'title':prefix,'endpoint':'fnlttSinglAcntAll','kind':'financial','fields':[]}
    found = []
    for schema in SCHEMAS:
        kind = schema.get('kind')
        term = normalize(schema['title'])
        hit = term in name
        if kind == 'securities':
            hit = '증권신고서' in name and term in name
        elif kind == 'insider':
            hit = '임원주요주주' in name and '소유상황' in name
        elif schema['endpoint'] == 'astInhtrfEtcPtbkOpt':
            hit = '자산양수도' in name or '풋백옵션' in name
        elif not kind and '증권신고서' in name:
            hit = False
        if hit:
            found.append((len(term), schema))
    return max(found, key=lambda item:item[0])[1] if found else None


def exact_rows(payload, receipt):
    rows = []
    def walk(node, inherited=None):
        if isinstance(node, dict):
            current = str(node.get('rcept_no', inherited))
            if current == receipt:
                rows.append(node)
            for value in node.values():
                if isinstance(value, (dict,list)):
                    walk(value,current)
        elif isinstance(node,list):
            for value in node:
                walk(value,inherited)
    walk(payload)
    return rows


def structured_fields(payload, receipt, schema):
    rows = exact_rows(payload, receipt)
    labels = {f['key']:f['label'] for f in reversed(schema['fields'])}
    keys = list(dict.fromkeys(PREFERRED.get(schema['endpoint'], ()) + tuple(labels)))
    result = []
    seen = set()
    data_rows = [row for row in rows if any(key in row for key in labels)]
    preferred = PREFERRED.get(schema['endpoint'], ())
    data_rows.sort(key=lambda row:-sum(key in row for key in preferred))
    for index,row in enumerate(data_rows,1):
        for key in keys:
            if key not in labels:
                continue
            value = row.get(key)
            if value is None or isinstance(value,(list,dict)) or str(value).strip() in ('','-'):
                continue
            label = labels[key] + (f' [항목{index}]' if len(data_rows)>1 else '')
            pair = (label, text(value))
            if pair not in seen:
                result.append(pair)
                seen.add(pair)
    return result[:9]


def label_key(value):
    value = re.sub(r'\((?:원|백만원|천원|억원|%|주|명|USD|KRW)\)', '', value, flags=re.I)
    return re.sub(r'[\s\d.,:()（）ㆍ·\-]', '', value)


class Tables(HTMLParser):
    """Keep table boundaries and expand rowspan/colspan; never execute or fetch document content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tables = []
        self.context = []
        self.row_count = 0
    def handle_starttag(self, tag, attrs):
        tag = tag.lower().split(':')[-1]
        attrs = dict(attrs)
        if tag == 'table':
            if len(self.stack) >= 20:
                raise ValueError('Table nesting exceeds memory budget')
            self.stack.append({'rows':[], 'row':None, 'cell':None, 'pending':{}, 'context':' '.join(self.context[-8:])})
        elif self.stack:
            frame = self.stack[-1]
            if tag == 'tr':
                self.row_count += 1
                if self.row_count > 4000:
                    raise ValueError('Table row budget exceeded')
                frame['row'] = []
            elif tag in ('td','th','te','tu') and frame['row'] is not None:
                def span(name):
                    try:
                        return min(50,max(1,int(attrs.get(name,1))))
                    except ValueError:
                        return 1
                frame['cell'] = {'parts':[], 'rowspan':span('rowspan'), 'colspan':span('colspan'), 'header':tag=='th'}
            elif tag in ('br','p') and frame['cell']:
                frame['cell']['parts'].append(' ')
    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell']:
            self.stack[-1]['cell']['parts'].append(data)
        elif not self.stack and data.strip():
            self.context.append(text(data,180))
            self.context = self.context[-8:]
    def handle_endtag(self, tag):
        tag = tag.lower().split(':')[-1]
        if not self.stack:
            return
        frame = self.stack[-1]
        if tag in ('td','th','te','tu') and frame['cell']:
            cell = frame['cell']
            frame['row'].append((text(''.join(cell['parts']),2000),cell['rowspan'],cell['colspan'],cell['header']))
            frame['cell'] = None
        elif tag == 'tr' and frame['row'] is not None:
            old = frame['pending']
            grid = {}
            headers = {}
            following = {}
            for column,(remaining,value,is_header) in old.items():
                grid[column],headers[column] = value,is_header
                if remaining > 1:
                    following[column] = (remaining-1,value,is_header)
            column = 0
            for value,rowspan,colspan,is_header in frame['row']:
                while column in grid:
                    column += 1
                for position in range(column,column+colspan):
                    if position in grid:
                        continue
                    grid[position],headers[position] = value,is_header
                    if rowspan > 1:
                        following[position] = (rowspan-1,value,is_header)
                column += colspan
            if grid:
                frame['rows'].append(([grid.get(i,'') for i in range(max(grid)+1)],headers))
            frame['pending'] = following
            frame['row'] = None
        elif tag == 'table':
            self.tables.append(self.stack.pop())


def raw_fields(document, aliases):
    if '<!ENTITY' in document.upper():
        raise ValueError('Entity declarations are unsupported')
    parser = Tables()
    parser.feed(document)
    result = []
    seen = set()
    for table_index, table in enumerate(parser.tables,1):
        unit = ''
        context = table['context']
        matches_unit = re.findall(r'단위\s*[:：]\s*[^)）\n]{1,80}',context)
        if matches_unit:
            unit = matches_unit[-1]
        headings = []
        for cells, header_flags in table['rows']:
            joined = ' '.join(cells)
            if '단위' in joined:
                unit = text(joined,100)
            if (any(header_flags.values()) and sum(bool(v) for v in header_flags.values()) >= len(cells)-1) or (len(cells)>1 and label_key(cells[0]) in ('구분','항목') and any(any(word in c for word in ('당기','전기','당해','전년','직전')) for c in cells[1:])):
                headings = cells
            for index, cell in enumerate(cells[:-1]):
                prefix = label_key(' '.join(cells[:index+1]))
                found = [alias for alias in aliases if label_key(alias) and (label_key(cell)==label_key(alias) or prefix.endswith(label_key(alias)))]
                if not found:
                    continue
                values = [(position,value) for position,value in enumerate(cells[index+1:],index+1) if value and value != cell]
                if not values:
                    continue
                label = max(found,key=len)
                if len(values)>1:
                    value = ' | '.join((headings[position]+': ' if position<len(headings) and headings[position] else f'열{position-index}: ')+v for position,v in values)
                else:
                    value = values[0][1]
                explicit_unit = re.search(r'\((원|백만원|천원|억원|%|주|명|USD|KRW)\)',cell,re.I)
                used_unit = explicit_unit.group(1) if explicit_unit else unit
                if used_unit:
                    value += ' ['+used_unit+']'
                pair = (label+' [표'+str(table_index)+']',text(value))
                if pair not in seen:
                    result.append(pair)
                    seen.add(pair)
    return result[:9]


def document_text(data, receipt):
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError('DART original document unavailable')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [info for info in archive.infolist() if not info.is_dir() and info.filename.lower().endswith(('.xml','.html','.htm'))]
        if len(names)>50 or sum(info.file_size for info in names)>MAX_XML:
            raise ValueError('Document exceeds memory budget')
        preferred = [info for info in names if Path(info.filename).stem==receipt]
        if preferred:
            target = preferred[0]
        elif len(names)==1:
            target = names[0]
        else:
            raise ValueError('Main document cannot be identified safely')
        body = archive.read(target)
        encoding = re.search(br'encoding=[\'\"]([^\'\"]+)',body[:300])
        declared = encoding.group(1).decode('ascii') if encoding else 'utf-8'
        if declared.lower() not in ('utf-8','utf8','euc-kr','cp949','ks_c_5601-1987'):
            raise ValueError('Unsupported document encoding')
        return body.decode(declared,errors='strict')


def financial_fields(payload, receipt):
    fields = []
    accounts = ('매출액','수익(매출액)','영업수익','영업이익','영업이익(손실)','당기순이익','당기순이익(손실)','자산총계','부채총계','자본총계')
    for row in exact_rows(payload,receipt):
        if row.get('account_nm') not in accounts or row.get('sj_div') not in ('BS','IS','CIS'):
            continue
        value = row.get('thstrm_amount')
        if value is None or str(value).strip() in ('','-'):
            continue
        basis={'CFS':'연결','OFS':'별도'}.get(row.get('fs_div'), '재무범위 미확인')
        statement={'BS':'재무상태표','IS':'손익계산서','CIS':'포괄손익계산서'}[row['sj_div']]
        label = basis+' '+statement+' '+row['account_nm']
        period = row.get('thstrm_nm','당기')
        currency = row.get('currency','통화 미확인')
        fields.append((label,f'{period}: {value} [{currency}]; 누적 여부는 원문 확인'))
    return list(dict.fromkeys(fields))[:9]


class Extractor:
    def __init__(self, key, store, daily_limit=18000):
        self.key,self.store,self.daily_limit = key,store,daily_limit
    def json(self, endpoint, params):
        self.store.reserve_dart_request(self.daily_limit)
        return request_json('OpenDART','https://opendart.fss.or.kr/api/'+endpoint+'.json?'+urlencode({'crtfc_key':self.key,**params}),timeout=8)
    def original(self, receipt):
        self.store.reserve_dart_request(self.daily_limit)
        request = urllib.request.Request('https://opendart.fss.or.kr/api/document.xml?'+urlencode({'crtfc_key':self.key,'rcept_no':receipt}),headers={'User-Agent':'GongsiBot/1.0'})
        with urllib.request.urlopen(request,timeout=8) as response:
            data = response.read(MAX_ZIP+1)
        if len(data)>MAX_ZIP:
            raise ValueError('Document exceeds download budget')
        return document_text(data,receipt)
    def extract(self, report):
        receipt = report['rcept_no']
        cache_key = 'extract_v1:'+receipt
        cached = self.store.get(cache_key)
        if cached:
            return cached
        schema = schema_for(report['report_nm'])
        fields = []
        if schema:
            try:
                params = {'corp_code':report['corp_code']}
                if schema.get('kind') == 'financial':
                    period = re.search(r'\((\d{4})\.(\d{2})\)',report['report_nm'])
                    if period:
                        year, month = period.groups()
                        code = {'사업보고서':'11011','반기보고서':'11012'}.get(schema['title'])
                        if schema['title']=='분기보고서':
                            code = {'03':'11013','09':'11014'}.get(month)
                        if code:
                            for basis in ('CFS','OFS'):
                                payload = self.json(schema['endpoint'],{**params,'bsns_year':year,'reprt_code':code,'fs_div':basis})
                                for row in payload.get('list',[]):
                                    if isinstance(row,dict):
                                        row.setdefault('fs_div',basis)
                                fields = financial_fields(payload,receipt)
                                if fields:
                                    break
                else:
                    if schema.get('kind') not in ('holdings','insider'):
                        params.update(bgn_de=report['rcept_dt'],end_de=report['rcept_dt'])
                    payload = self.json(schema['endpoint'],params)
                    if payload.get('status')=='000':
                        fields = structured_fields(payload,receipt,schema)
            except Exception:
                fields = []
        if fields:
            result = {'source':'OpenDART 구조화 정보','fields':fields}
        else:
            name = normalize(report['report_nm'])
            profiles = [p for p in RAW_PROFILES if any(normalize(term) in name for term in p[1])]
            aliases = [f['label'] for f in schema['fields']] if schema else []
            if profiles:
                aliases += list(profiles[0][2])
            if schema and schema.get('kind')=='financial':
                aliases += ['매출액','영업이익','당기순이익','자산총계','부채총계','자본총계']
            if not aliases:
                aliases = ['제목','주요내용','발생일자','결정내용','금액','기간']
            try:
                fields = raw_fields(self.original(receipt),aliases)
            except Exception:
                fields = []
            result = {'source':'원문 표' if fields else '추출 불가 · 원문 확인','fields':fields}
        if result['fields']:
            self.store.set(cache_key,result)
        return result


def format_notification(report, summary=None):
    # Use one conservative message budget; supplementary text never displaces the source link.
    lines = [f"[{text(report.get('corp_name',''),80)}] {text(report['report_nm'],220)}",
             '접수일: '+report['rcept_dt']]
    if summary:
        lines.append('주요항목 발췌 · '+summary['source'])
        for label,value in summary.get('fields',[])[:9]:
            lines.append('• '+text(label,90)+': '+text(value,230))
        lines.append('전체 내용·조건·정정 여부는 원문에서 확인하세요.')
    lines.append('https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+report['rcept_no'])
    while len('\n'.join(lines).encode('utf-16-le'))//2 > 3800 and len(lines)>5:
        lines.pop(-3)
    return '\n'.join(lines)
