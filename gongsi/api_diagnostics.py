"""Bounded, read-only probes for explicitly requested public filing diagnostics."""
import json
from .api import now_kst,ApiError
from .extraction import schema_for,exact_rows,structured_fields

TARGETS=('20261026800210','20261026800116')
KEY='api_probe_20261026_v1'


def run_probe(bot,store):
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