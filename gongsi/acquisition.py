"""API-first acquisition with explicit evidence and safe field-level supplementation."""
from datetime import datetime,timedelta
import re
from .api import ApiError
from .presentation import CONTRACTS


def canonical(label):
    from .extraction import label_key
    return label_key(re.sub(r' \[(?:표|항목)\d+\]$','',label))


def contract_labels(schema):
    labels={f['key']:f['label'] for f in schema['fields']}
    return [(k,labels[k],name) for k,name in CONTRACTS.get(schema['endpoint'],[]) ]


def missing_core(schema,fields):
    present={canonical(l) for l,v in fields}
    return [label for key,label,name in contract_labels(schema)
            if 'estk' not in key and 'cstk' not in key and 'fdpp_' not in key
            and canonical(label) not in present]


def api_fields(extractor,report,schema):
    from .extraction import exact_rows,structured_fields,financial_fields
    evidence={'endpoint':schema['endpoint'] if schema else None,'attempts':[],
              'reason':'no_structured_api' if not schema else 'not_queried'}
    if not schema: return [],evidence
    base={'corp_code':report['corp_code']}
    queries=[]
    financial=schema.get('kind')=='financial'
    if financial:
        match=re.search(r'\((\d{4})\.(\d{2})\)',report['report_nm'])
        code=None
        if match:
            year,month=match.groups()
            code={'사업보고서':'11011','반기보고서':'11012'}.get(schema['title'])
            if schema['title']=='분기보고서': code={'03':'11013','09':'11014'}.get(month)
            if code: queries=[{**base,'bsns_year':year,'reprt_code':code,'fs_div':basis} for basis in ('CFS','OFS')]
        if not queries:
            evidence['reason']='financial_period_unresolved'
            return [],evidence
    elif schema.get('kind') in ('holdings','insider'):
        queries=[base]
    else:
        day=report['rcept_dt']
        earlier=(datetime.strptime(day,'%Y%m%d')-timedelta(days=31)).strftime('%Y%m%d')
        queries=[{**base,'bgn_de':start,'end_de':day} for start in (day,earlier)]
    for params in queries:
        attempt={k:v for k,v in params.items() if k!='corp_code'}
        try:
            payload=extractor.json(schema['endpoint'],params)
            status=str(payload.get('status','invalid'))
            # Do not store API message strings or raw exceptions: they may contain secrets.
            attempt['status']=status if re.fullmatch(r'[0-9]{3}',status) else 'invalid'
            exact=exact_rows(payload,report['rcept_no']) if status=='000' else []
            if financial:
                for row in payload.get('list',[]):
                    if isinstance(row,dict): row.setdefault('fs_div',params['fs_div'])
                fields=financial_fields(payload,report['rcept_no']) if status=='000' else []
            else:
                fields=structured_fields(payload,report['rcept_no'],schema) if status=='000' else []
                allowed={canonical(label) for key,label,name in contract_labels(schema)}
                fields=[(l,v) for l,v in fields if canonical(l) in allowed]
            attempt.update(exact_receipt_rows=len(exact),field_count=len(fields))
            reason=('api_fields_available' if fields else 'receipt_not_returned' if status=='000' and not exact else 'contract_fields_missing' if status=='000' else 'no_data' if status=='013' else 'api_error')
            attempt['reason']=reason
            evidence['attempts'].append(attempt);evidence['reason']=reason
            if fields: return fields,evidence
            # A second date/basis query is useful only for empty results, not key/quota errors.
            if status not in ('000','013'): break
        except Exception as exc:
            code=exc.code if isinstance(exc,ApiError) else type(exc).__name__
            attempt.update(reason='request_error',error_code=str(code) if re.fullmatch(r'[A-Za-z0-9_-]{1,40}',str(code)) else 'redacted_error')
            evidence['attempts'].append(attempt);evidence['reason']='request_error'
            break
    return [],evidence


def supplement(api,original):
    """Never replace API values or mix multiple security records with ungrouped raw data."""
    if any(re.search(r' \[항목\d+\]$',l) for l,v in api):
        return list(api),[],int(bool(original))
    present={canonical(l) for l,v in api}
    candidates={}
    for label,value in original:
        name=canonical(label)
        if name not in present:
            candidates.setdefault(name,[]).append((label,value))
    additions=[];withheld=0
    for pairs in candidates.values():
        values={v for l,v in pairs}
        if len(values)!=1:
            withheld+=1
            continue
        label,value=pairs[0]
        additions.append((re.sub(r' \[표\d+\]$','',label),value))
    return list(api)+additions,additions,withheld


def acquire(extractor,report):
    from .extraction import schema_for,RAW_PROFILES,normalize,raw_fields
    from .api import now_kst
    schema=schema_for(report['report_nm'])
    api,evidence=api_fields(extractor,report,schema)
    result={'fields':list(api),'source':'OpenDART 구조화 정보' if api else '추출 불가 · 원문 확인',
            'evidence':evidence,'field_sources':[{'label':l,'source':'structured_api'} for l,v in api],
            'checked_at':now_kst().isoformat(timespec='seconds')}
    missing=missing_core(schema,api) if schema and schema.get('kind')!='financial' else []
    needs_raw=not api or bool(missing)
    if needs_raw:
        evidence['original_reason']='api_partial_fields' if api else evidence['reason']
        aliases=[f['label'] for f in schema['fields']] if schema else []
        name=normalize(report['report_nm'])
        profile=next((p for p in RAW_PROFILES if any(normalize(t) in name for t in p[1])),None)
        if profile: aliases+=list(profile[2])
        if schema and schema.get('kind')=='financial':
            aliases+=['매출액','영업이익','당기순이익','자산총계','부채총계','자본총계']
        if not aliases: aliases=['제목','주요내용','발생일자','결정내용','금액','기간']
        try:
            from .original_source import original_fields
            original=original_fields(extractor,report['rcept_no'],aliases,evidence)
            evidence['original_field_count']=len(original)
            if not api and not original and report['report_nm'].lstrip().startswith('[첨부정정]'):
                from .original_source import parent_reference
                import json
                parent=parent_reference(extractor,report['rcept_no'])
                with extractor.store.lock:
                    row=extractor.store.db.execute('SELECT data FROM reports WHERE receipt=?',(parent,)).fetchone() if parent else None
                linked=json.loads(row[0]) if row else None
                linked_schema=schema_for(linked['report_nm']) if linked else None
                if (linked and linked.get('corp_code')==report.get('corp_code') and schema and linked_schema
                        and linked_schema['endpoint']==schema['endpoint']):
                    reference_evidence={}
                    original=original_fields(extractor,parent,aliases,reference_evidence)
                    if original:
                        result['reference_receipt']=parent
                        evidence['reference_evidence']=reference_evidence
            raw_withheld=getattr(original,'withheld',0)
            if api:
                # Only missing fields in the same explicit contract may supplement an API record.
                original=[(l,v) for l,v in original if canonical(l) in {canonical(x) for x in missing}]
                fields,added,ambiguous=supplement(api,original)
                result['fields']=fields
                if added:
                    result['source']='OpenDART 구조화 정보 + 원문 표 보완'
                    result['field_sources'] += [{'label':l,'source':'original_table'} for l,v in added]
                result['withheld']=raw_withheld+ambiguous
            else:
                result['fields']=list(original)
                result['withheld']=getattr(original,'withheld',0)
                if original: result['source']='원문 표'
                result['field_sources']=[{'label':l,'source':'original_table'} for l,v in original]
        except Exception as exc:
            evidence['original_error']=type(exc).__name__
    if result.get('reference_receipt'):
        result['source']='이전 본문 참고 · 첨부정정은 원문 확인'
        result['field_sources']=[{'label':l,'source':'reference_original','receipt':result['reference_receipt']} for l,v in result['fields']]
    result['missing_contract_fields']=missing_core(schema,result['fields']) if schema and schema.get('kind')!='financial' else []
    # Evidence is durable even when extraction fails, but failure results are not cached.
    extractor.store.set('extraction_evidence:'+report['rcept_no'],result)
    return result