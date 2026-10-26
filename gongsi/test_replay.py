"""Explicit, date-limited owner test requests delivered once through the normal bot worker."""
import json
from pathlib import Path
import re
from .api import now_kst
from .catalog import matches
from .extraction import format_notification
from .runtime_reports import send_recorded

REQUESTS=Path(__file__).with_name('test_requests.json')


def process_requests(bot,store,stop,requests=None):
    if bot.owner_id != 6766930417:
        return
    if requests is None:
        requests=json.loads(REQUESTS.read_text(encoding='utf-8')) if REQUESTS.is_file() else []
    today=now_kst().date().isoformat()
    for request in requests[:5]:
        identifier=request.get('id','')
        if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',identifier) or request.get('date') != today:
            continue
        count=request.get('count')
        if not isinstance(count,int) or isinstance(count,bool) or not 1 <= count <= 10:
            continue
        all_today=request.get('all_today',False)
        if not isinstance(all_today,bool):
            continue
        distinct=request.get('distinct_companies',not all_today)
        if not isinstance(distinct,bool):
            continue
        target=request.get('company')
        if target is not None and (not isinstance(target,str) or not target.strip() or len(target)>80):
            continue
        receipt_filter=request.get('receipt')
        if receipt_filter is not None and (not isinstance(receipt_filter,str) or not re.fullmatch('[0-9]{14}',receipt_filter) or count!=1):
            continue
        key='test_replay:'+identifier
        state=store.get(key)
        if state and state.get('done'):
            continue
        if not state:
            selected=store.settings()['selected']
            reports=[]
            companies=set()
            with store.lock:
                for row in store.db.execute('SELECT data FROM reports ORDER BY receipt DESC'):
                    report=json.loads(row[0])
                    company=report.get('corp_code') or report.get('corp_name')
                    if (report.get('rcept_dt')==today.replace('-','')
                            and (receipt_filter is None or report.get('rcept_no')==receipt_filter)
                            and (not distinct or company not in companies)
                            and ((target is not None and report.get('corp_name')==target)
                                 or (target is None and matches(report.get('report_nm',''),selected)))):
                        reports.append(report)
                        companies.add(company)
                        if not all_today and len(reports)==count:
                            break
            if not reports:
                store.set('test_replay_last',{'id':identifier,'sent':0,'requested':count,'status':'waiting_for_filings'})
                continue
            state={'reports':reports,'next':0,'message_ids':[],'done':False}
            store.set(key,state)
        total=len(state['reports'])
        end=min(state['next']+3,total) if all_today else total
        store.set('test_replay_last',{'id':identifier,'sent':state['next'],'requested':total if all_today else count,'status':'sending'})
        for index in range(state['next'],end):
            if stop.is_set():
                return
            report=state['reports'][index]
            summary=None
            extractor=getattr(bot,'extractor',None)
            if extractor is not None:
                try:
                    summary=extractor.extract(report)
                except Exception:
                    summary={'source':'추출 불가 · 원문 확인','fields':[]}
            message=f'[테스트 재전송 {index+1}/{len(state["reports"])}]\\n'
            message=message.replace('\\n','\n')+format_notification(report,summary,html=True)
            response=send_recorded(bot,store,report,summary,message,'test_replay')
            state['next']=index+1
            state['message_ids'].append(response.get('message_id'))
            state['done']=state['next']==len(state['reports'])
            store.set(key,state)
            store.set('test_replay_last',{'id':identifier,'sent':state['next'],'requested':total if all_today else count,
                                         'status':'completed' if state['done'] else 'sending'})
            if stop.wait(1.3):
                return
