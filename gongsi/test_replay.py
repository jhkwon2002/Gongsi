"""Explicit, date-limited owner test requests delivered once through the normal bot worker."""
import json
from pathlib import Path
import re
from .api import now_kst
from .catalog import matches
from .extraction import format_notification

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
        if not isinstance(count,int) or isinstance(count,bool) or not 1 <= count <= 5:
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
                    if (report.get('rcept_dt')==today.replace('-','') and company not in companies
                            and matches(report.get('report_nm',''),selected)):
                        reports.append(report)
                        companies.add(company)
                        if len(reports)==count:
                            break
            if not reports:
                store.set('test_replay_last',{'id':identifier,'sent':0,'requested':count,'status':'waiting_for_filings'})
                continue
            state={'reports':reports,'next':0,'message_ids':[],'done':False}
            store.set(key,state)
        for index in range(state['next'],len(state['reports'])):
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
            response=bot.send(message,parse_mode='HTML')
            state['next']=index+1
            state['message_ids'].append(response.get('message_id'))
            state['done']=state['next']==len(state['reports'])
            store.set(key,state)
            store.set('test_replay_last',{'id':identifier,'sent':state['next'],'requested':count,
                                         'status':'completed' if state['done'] else 'sending'})
            if stop.wait(1.3):
                return
