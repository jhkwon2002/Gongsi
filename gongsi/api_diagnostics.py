"""Bounded, read-only probes for explicitly requested public filing diagnostics."""
import json
from .api import now_kst,ApiError
from .extraction import schema_for,exact_rows,structured_fields

TARGETS=('20261026800210','20261026800116','20261026000318')
KEY='api_probe_20261026_v2'


def run_probe(bot,store):
    run_encoding_probe(bot,store,now_kst())
    run_original_probe(bot,store,now_kst())
    run_structure_probe(bot,store,now_kst())
    run_routing_recheck(bot,store,now_kst())
    if now_kst().date().isoformat()!='2026-10-26': return
    previous=store.get(KEY,{})
    if previous.get('complete') or previous.get('attempts',0)>=3: return
    # Retry transient failures at most once per five minutes; never send Telegram messages.
    now=now_kst()
    if previous.get('retry_after') and now.timestamp()<previous['retry_after']: return
    extractor=getattr(bot,'extractor',None)
    if extractor is None: return
    results=[]
    transient=False
    for receipt in TARGETS:
        with store.lock:
            row=store.db.execute('SELECT data FROM reports WHERE receipt=?',(receipt,)).fetchone()
        if not row:
            results.append({'receipt':receipt,'reason':'report_not_in_database'})
            continue
        report=json.loads(row[0])
        schema=schema_for(report['report_nm'])
        result={'receipt':receipt,'company':report.get('corp_name','')[:80],
                'title':report['report_nm'][:220],'endpoint':schema['endpoint'] if schema else None,'queries':[]}
        if not schema:
            result['reason']='no_schema'
            results.append(result)
            continue
        for start in ('20261026','20261001'):
            query={'start':start,'end':'20261026'}
            try:
                payload=extractor.json(schema['endpoint'],{'corp_code':report['corp_code'],'bgn_de':start,'end_de':'20261026'})
                status=str(payload.get('status','invalid'))
                rows=exact_rows(payload,receipt)
                fields=structured_fields(payload,receipt,schema) if status=='000' else []
                candidates=payload.get('list',[])
                from .presentation import CONTRACTS
                labels={f['key']:f['label'] for f in schema['fields']}
                allowed={labels[k] for k,n in CONTRACTS[schema['endpoint']]}
                query['public_api_fields']=[{'label':l,'value':v} for l,v in fields if l in allowed][:10]
                query.update(status=status,matching_receipt_rows=len(rows),extracted_field_count=len(fields),
                             returned_receipts=sorted(set(str(r['rcept_no']) for r in candidates if isinstance(r,dict) and str(r.get('rcept_no','')).isdigit() and len(str(r['rcept_no']))==14))[:20])
                query['reason']=('structured_fields_available' if fields else 'receipt_not_returned' if status=='000' and not rows else 'matching_row_has_no_fields' if status=='000' else 'no_data' if status=='013' else 'api_status_error')
                if status not in ('000','013'): transient=True
            except Exception as exc:
                transient=True
                query.update(reason='request_failed',error_code=exc.code if isinstance(exc,ApiError) else type(exc).__name__)
            result['queries'].append(query)
        results.append(result)
    store.set(KEY,{'checked_at':now.isoformat(timespec='seconds'),'release':store.get('release','unknown'),
                   'attempts':previous.get('attempts',0)+1,'complete':not transient,
                   'retry_after':now.timestamp()+300,'results':results,
                   'note':'Read-only re-query; describes current API responses, not a recovered historical response. No Telegram replay.'})


ORIGINAL_KEY='original_probe_20261027_v1'


def run_original_probe(bot,store,now):
    """Check the reported HD filing without sending or changing delivery state."""
    if now.date().isoformat()!='2026-10-27': return
    previous=store.get(ORIGINAL_KEY,{})
    if previous.get('complete') or previous.get('attempts',0)>=3: return
    if now.timestamp()<previous.get('retry_after',0): return
    extractor=getattr(bot,'extractor',None)
    if extractor is None: return
    receipt='20261027800235'
    with store.lock:
        row=store.db.execute('SELECT data FROM reports WHERE receipt=?',(receipt,)).fetchone()
    if not row: return
    from .acquisition import acquire
    from .presentation import present
    report=json.loads(row[0])
    try:
        summary=acquire(extractor,report)
        fields=present(report,summary)
        result={'receipt':receipt,'company':report.get('corp_name','')[:80],
                'title':report['report_nm'][:220],'fields':[{'label':l,'value':v} for l,v in fields[:10]],
                'evidence':summary['evidence'],'complete':bool(fields)}
    except Exception as exc:
        result={'receipt':receipt,'complete':False,'error_type':type(exc).__name__}
    result.update(checked_at=now.isoformat(timespec='seconds'),release=store.get('release','unknown'),
                  attempts=previous.get('attempts',0)+1,retry_after=now.timestamp()+300,
                  note='Read-only original extraction diagnosis; no Telegram replay.')
    store.set(ORIGINAL_KEY,result)


def run_structure_probe(bot,store,now):
    if now.date().isoformat()!='2026-10-27': return
    key='structure_probe_20261027_v1'
    if store.get(key): return
    from .original_source import read_html,viewer_params,failure
    import re
    from html.parser import HTMLParser
    class Page(HTMLParser):
        def __init__(self):
            super().__init__();self.links=[];self.words=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag in ('iframe','frame','a','option'):
                for name in ('src','href','value'):
                    value=a.get(name,'')
                    if any(s in value for s in ('viewer','rcpNo','rcpno','dcmNo','disclsviewer')):
                        from urllib.parse import urlsplit,parse_qsl
                        u=urlsplit(value)
                        if u.hostname and u.hostname not in ('dart.fss.or.kr','kind.krx.co.kr'): continue
                        self.links.append({'tag':tag,'path':u.path,'host':u.hostname,
                            'params':{k:v for k,v in parse_qsl(u.query) if k.lower() in ('rcpno','dcmno','eleid','offset','length','dtd','acptno','docno','method')}})
        def handle_data(self,data):
            s=data.strip()
            if s and len(s)<500 and any(w in s for w in ('정정','합병','보고서','최초')): self.words.append(s[:200])
    results=[]
    for receipt in ('20261027800573','20261027800571','20261027800546','20261027000306'):
        item={'receipt':receipt}
        try:
            bot.extractor.store.reserve_dart_request(bot.extractor.daily_limit)
            page=read_html('https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt)
            parser=Page();parser.feed(page)
            item.update(length=len(page),links=parser.links[:20],
                literals=re.findall(r'(?:viewDoc|openReport|openViewer)\([^\n;]{0,300}',page)[:10],
                nodes=re.findall(r"node\d+\[['\"](?:text|rcpNo|rceptNo|dcmNo|eleId|offset|length|dtd)['\"]\]\s*=\s*[^;\n]{0,200}",page)[:40],
                related=parser.words[:8])
            try:
                params=viewer_params(page,receipt);item['viewer']=params
                from urllib.parse import urlencode
                bot.extractor.store.reserve_dart_request(bot.extractor.daily_limit)
                body=read_html('https://dart.fss.or.kr/report/viewer.do?'+urlencode(params))
                p=Page();p.feed(body)
                item['body_related']=p.words[:15];item['body_links']=p.links[:20]
            except Exception as exc: item['viewer_error']=failure(exc,'viewer')
        except Exception as exc: item['error']=failure(exc,'main')
        results.append(item)
    store.set(key,{'release':store.get('release'),'checked_at':now.isoformat(),'results':results})


def run_routing_recheck(bot,store,now):
    if now.date().isoformat()!='2026-10-27' or store.get('routing_recheck_v1'): return
    from .acquisition import acquire
    from .presentation import present
    results=[]
    for receipt in ('20261027800573','20261027800571','20261027800546','20261027000306'):
        with store.lock:
            row=store.db.execute('SELECT data FROM reports WHERE receipt=?',(receipt,)).fetchone()
        if not row: continue
        report=json.loads(row[0])
        try:
            summary=acquire(bot.extractor,report)
            results.append({'receipt':receipt,'company':report.get('corp_name'),
                'source':summary['source'],'reference_receipt':summary.get('reference_receipt'),
                'fields':[{'label':l,'value':v} for l,v in present(report,summary)[:12]],
                'evidence':summary['evidence']})
        except Exception as exc:
            results.append({'receipt':receipt,'error_type':type(exc).__name__})
    store.set('routing_recheck_v1',{'checked_at':now.isoformat(),'release':store.get('release'),'results':results})


ENCODING_KEY='encoding_probe_nhn_20261030_v1'


def run_encoding_probe(bot,store,now):
    """Three bounded read-only attempts on the requested NHN filing; no replay."""
    if not '2026-10-30' <= now.date().isoformat() <= '2026-11-01':
        return
    previous=store.get(ENCODING_KEY,{})
    if previous.get('complete') or previous.get('attempts',0)>=3:
        return
    if now.timestamp()<previous.get('retry_after',0):
        return
    extractor=getattr(bot,'extractor',None)
    if extractor is None:
        return
    receipt='20261029800841'
    result={'receipt':receipt,'checked_at':now.isoformat(timespec='seconds'),
            'release':store.get('release','unknown'),'attempts':previous.get('attempts',0)+1,
            'retry_after':now.timestamp()+300,'complete':False,
            'note':'Read-only original recheck; no Telegram send or delivery-state change.'}
    with store.lock:
        row=store.db.execute('SELECT data FROM reports WHERE receipt=?',(receipt,)).fetchone()
    if not row:
        result['reason']='report_not_in_database'
        store.set(ENCODING_KEY,result)
        return
    report=json.loads(row[0])
    schema=schema_for(report['report_nm'])
    if report.get('corp_name')!='NHN' or not schema or schema['endpoint']!='otcprStkInvscrTrfDecsn':
        result['reason']='report_identity_mismatch'
        store.set(ENCODING_KEY,result)
        return
    from .original_source import original_fields,failure
    from .presentation import present
    evidence={}
    result.update(company='NHN',title=report['report_nm'][:220],evidence=evidence)
    try:
        fields=original_fields(extractor,receipt,[f['label'] for f in schema['fields']],evidence)
        display=present(report,{'source':'원문 표','fields':fields})
        result.update(extracted_field_count=len(fields),
                      fields=[{'label':label,'value':value} for label,value in display[:12]],
                      complete=bool(display),reason='fields_available' if display else 'no_display_fields')
    except Exception as exc:
        result.update(reason='original_failed',error=failure(exc,'original_recheck'))
    store.set(ENCODING_KEY,result)
