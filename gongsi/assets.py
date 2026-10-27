"""Company asset bounds, exact-receipt financial lookup, and persistent controls."""
import re
from decimal import Decimal
from .api import now_kst, ApiError

PRESETS=(100,500,1000,3000,5000,10000,30000,50000,100000,500000)
DEFAULT={'min':None,'max':None,'unknown':False}

def config(store):
    return {**DEFAULT,**store.settings().get('assets',{})}

def amount(text):
    m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(조원?|억원?|원)?',text.replace(',','').strip())
    if not m: raise ValueError('금액 형식')
    n=Decimal(m[1])*({'조':10**12,'조원':10**12,'억':10**8,'억원':10**8,'원':1,None:10**8}[m[2]])
    if n!=int(n) or not 0<=n<=10**18: raise ValueError('금액 범위')
    return int(n)

def money(n):
    if n is None: return '제한 없음'
    unit,scale=('조원',10**12) if n>=10**12 else ('억원',10**8)
    return format(Decimal(n)/scale,'f').rstrip('0').rstrip('.')+unit if n%scale else str(n//scale)+unit

def description(c):
    if c['min'] is None and c['max'] is None: return '자산총액: 제한 없음'
    return '자산총액: '+money(c['min'])+' 이상 / '+money(c['max'])+' 이하'

def change(store,field,value,revision):
    with store.lock:
        p=store.settings()
        if p['revision']!=revision: return False
        c={**DEFAULT,**p.get('assets',{})}
        if field=='reset': c=dict(DEFAULT)
        elif field=='unknown':
            if type(value) is not bool: raise ValueError('자료 없음 설정')
            c[field]=value
        elif field in ('min','max'):
            if value is not None and (type(value) is not int or not 0<=value<=10**18): raise ValueError('금액 범위')
            c[field]=value
        else: raise ValueError('설정 항목')
        if c['min'] is not None and c['max'] is not None and c['min']>c['max']: raise ValueError('최소 금액이 최대 금액보다 큽니다')
        p['assets']=c;p['revision']+=1;store.set('settings',p)
        return True

def lookup(extractor,corp):
    now=now_kst();key='assets_v1:'+corp
    cache=extractor.store.get(key)
    if cache and now.timestamp()<cache['expires']: return cache['data']
    if not re.fullmatch(r'\d{8}',corp): return None
    payload=extractor.json('list',{'corp_code':corp,'bgn_de':str(now.year-2)+'0101',
        'end_de':now.strftime('%Y%m%d'),'pblntf_ty':'A','last_reprt_at':'Y',
        'sort':'date','sort_mth':'desc','page_count':100,'page_no':1})
    if payload.get('status') not in ('000','013'): raise ApiError('OpenDART',payload.get('status','invalid'))
    reports=[]
    for r in payload.get('list',[]):
        m=re.search(r'(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)',r.get('report_nm',''))
        if m and r.get('corp_code')==corp and re.fullmatch(r'\d{14}',r.get('rcept_no','')):
            reports.append((m,r))
    reports.sort(key=lambda x:(x[0][2],x[0][3],x[1]['rcept_no']),reverse=True)
    data=None;calls=0
    for m,r in reports[:3]:
        codes={'사업보고서':['11011'],'반기보고서':['11012'],
               '분기보고서':['11013','11014'] if m[3] not in ('03','09') else ['11013' if m[3]=='03' else '11014']}[m[1]]
        for basis in ('CFS','OFS'):
            for year in (int(m[2]),int(m[2])-1):
                for code in codes:
                    if calls>=8: break
                    calls+=1
                    out=extractor.json('fnlttSinglAcntAll',{'corp_code':corp,'bsns_year':str(year),'reprt_code':code,'fs_div':basis})
                    if out.get('status') not in ('000','013'): raise ApiError('OpenDART',out.get('status','invalid'))
                    values=set()
                    for row in out.get('list',[]):
                        if (row.get('rcept_no')!=r['rcept_no'] or row.get('corp_code')!=corp
                            or row.get('sj_div')!='BS' or row.get('currency')!='KRW'
                            or str(row.get('bsns_year'))!=str(year) or row.get('reprt_code')!=code): continue
                        if row.get('account_id') not in ('ifrs-full_Assets','ifrs_Assets') and re.sub(r'\s','',row.get('account_nm',''))!='자산총계': continue
                        value=str(row.get('thstrm_amount','')).replace(',','').strip()
                        if re.fullmatch(r'\d+',value): values.add(int(value))
                    if len(values)==1:
                        data={'amount':values.pop(),'basis':basis,'report':r['report_nm'],
                              'receipt':r['rcept_no'],'currency':'KRW'};break
                if data: break
            if data: break
        if data or calls>=8: break
    extractor.store.set(key,{'expires':now.timestamp()+(3600 if data else 300),'data':data})
    return data

def check(extractor,report,c):
    if c['min'] is None and c['max'] is None: return True,None
    if extractor is None: raise ApiError('OpenDART','asset_lookup_unavailable')
    data=lookup(extractor,report.get('corp_code',''))
    if data is None: return c['unknown'],None
    n=data['amount']
    return (c['min'] is None or n>=c['min']) and (c['max'] is None or n<=c['max']),data

def menu(store,field=None):
    c=config(store);rev=store.settings()['revision'];rows=[]
    if field in ('min','max'):
        text=('최소' if field=='min' else '최대')+' 자산총액을 선택하세요 (경계 포함)'
        buttons=[{'text':money(n*10**8),'callback_data':f'av:{field}:{n}:{rev}'} for n in PRESETS]
        rows=[buttons[i:i+2] for i in range(0,len(buttons),2)]
        rows.append([{'text':'제한 없음','callback_data':f'av:{field}:x:{rev}'}])
        rows.append([{'text':'↩ 자산 설정','callback_data':'a:home'}])
    else:
        text=description(c)+'\n선택한 보고서와 자산 조건을 모두 만족해야 자동 발송됩니다.\n최근 조회 가능한 정기보고서 · 연결 우선, 없으면 별도 · 원화 기준\n자산 자료 없는 기업: '+('포함' if c['unknown'] else '제외')+'\n직접 설정: /assets 1000억 5조 (최소 최대, 제한 없음은 -)\n변경 후 발견되는 공시부터 적용하며 과거 공시는 재전송하지 않습니다.'
        rows=[[{'text':'최소: '+money(c['min']),'callback_data':'a:min'},{'text':'최대: '+money(c['max']),'callback_data':'a:max'}],
              [{'text':'자료 없는 기업 '+('제외' if c['unknown'] else '포함'),'callback_data':f'av:unknown:{0 if c["unknown"] else 1}:{rev}'}],
              [{'text':'자산 제한 해제','callback_data':f'av:reset:x:{rev}'}],
              [{'text':'↩ 보고서 선택','callback_data':'p:-1'}]]
    return text,{'inline_keyboard':rows}


def heading_amount(n):
    """Truncate to whole eok won, then split into jo and eok."""
    eok=int(n)//100000000
    jo,eok=divmod(eok,10000)
    return (str(jo)+'조 '+format(eok,',')+'억원') if jo else format(eok,',')+'억원'
