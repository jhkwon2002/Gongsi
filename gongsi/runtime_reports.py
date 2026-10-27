"""Durable, public-data-only delivery ledger and outbound GitHub reporting."""
import hashlib
import json
import logging
import os
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request,urlopen
from .api import now_kst

LOG=logging.getLogger('gongsi')
REPO='jhkwon2002/Gongsi'
BRANCH='runtime-reports'
REPORT_PATH='runtime/latest.json'
API='https://api.github.com/repos/'+REPO


def record(store, report, summary, status, context):
    source=str((summary or {}).get('source',''))
    method=('structured_api_with_original' if '원문 표 보완' in source else 'structured_api' if 'OpenDART 구조화' in source else 'original_table' if source=='원문 표' else 'unavailable')
    row={'receipt':report['rcept_no'],'company':str(report.get('corp_name',''))[:80],
         'title':str(report.get('report_nm',''))[:220], 'filing_date':report.get('rcept_dt',''),
         'method':method,'status':status,'context':context,
         'release':store.get('release','unknown'),'recorded_at':now_kst().isoformat(timespec='seconds'),
         'withheld':bool((summary or {}).get('withheld')),
         'api_evidence':(summary or {}).get('evidence'),
         'field_sources':(summary or {}).get('field_sources',[])}
    # No token, preferences, Telegram chat/message IDs, paths, raw exceptions or raw document data.
    with store.tx() as db:
        db.execute('CREATE TABLE IF NOT EXISTS delivery_history (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)')
        db.execute('INSERT INTO delivery_history(data) VALUES (?)',(json.dumps(row,ensure_ascii=True),))
        db.execute('DELETE FROM delivery_history WHERE seq NOT IN (SELECT seq FROM delivery_history ORDER BY seq DESC LIMIT 1000)')


def send_recorded(bot,store,report,summary,message,context):
    try:
        response=bot.send(message,parse_mode='HTML')
    except Exception:
        record(store,report,summary,'send_failed',context)
        raise
    status='telegram_accepted' if isinstance(response,dict) and response.get('message_id') else 'send_returned_without_id'
    record(store,report,summary,status,context)
    return response


def snapshot(store):
    with store.lock:
        exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_history'").fetchone()
        rows=store.db.execute('SELECT data FROM delivery_history ORDER BY seq DESC LIMIT 200').fetchall() if exists else []
    history=[json.loads(row[0]) for row in rows]
    # Historical requests predate the ledger. Never call them confirmed sends.
    legacy=[]
    with store.lock:
        plans=store.db.execute("SELECT value FROM kv WHERE key LIKE 'test_replay:%'").fetchall()
    receipts={(r['receipt'],r['context']) for r in history}
    for row in plans:
        plan=json.loads(row[0])
        for index,report in enumerate(plan.get('reports',[])):
            context='test_replay'
            if (report.get('rcept_no'),context) in receipts:
                continue
            cached=next((value for value in (store.get(prefix+report['rcept_no']) for prefix in ('extract_v5:','extract_v4:','extract_v3:','extract_v2:','extract_v1:')) if value),None)
            source=str((cached or {}).get('source',''))
            legacy.append({'receipt':report['rcept_no'],'company':str(report.get('corp_name',''))[:80],
                           'title':str(report.get('report_nm',''))[:220],
                           'method':'structured_api' if 'OpenDART 구조화' in source else 'original_table' if source=='원문 표' else 'unknown',
                           'status':'historical_api_acknowledged' if index<len(plan.get('message_ids',[])) and plan['message_ids'][index] else 'historical_unverified',
                           'method_evidence':'extraction_cache_only','context':context})
    return {'schema_version':1,'release':store.get('release','unknown'),
            'last_scan_success':store.get('last_scan_success'),
            'delivery_history':history,'historical_replays':legacy[:100],
            'replay_progress':store.get('test_replay_last'),
            'structure_diagnostics':store.get('structure_probe_20261027_v1'),
            'original_diagnostics':store.get('original_probe_20261027_v1'),
            'api_diagnostics':store.get('api_probe_20261026_v2',store.get('api_probe_20261026_v1')),
            'note':'telegram_accepted means Telegram API accepted; it does not prove the user read it. Historical cache does not prove the method of a past message.'}


class GitHubError(Exception):
    def __init__(self,code): self.code=str(code);super().__init__('GitHub report: '+self.code)


class Publisher:
    def __init__(self,store,token=None):
        self.store=store
        self.token=token if token is not None else os.environ.get('GITHUB_REPORT_TOKEN','').strip()
        self.next_check=0

    def request(self,path,method='GET',data=None):
        body=json.dumps(data).encode() if data is not None else None
        req=Request(API+path,data=body,method=method,headers={'Authorization':'Bearer '+self.token,
                    'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'GongsiRuntimeReports'})
        try:
            with urlopen(req,timeout=8) as response:
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024: raise GitHubError('response_too_large')
            return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raise GitHubError(exc.code) from None
        except GitHubError:
            raise
        except Exception:
            raise GitHubError('network_error') from None

    def publish(self,payload):
        import base64
        encoded=json.dumps(payload,ensure_ascii=True,sort_keys=True,indent=2)+'\n'
        digest=hashlib.sha256(encoded.encode()).hexdigest()
        if digest==self.store.get('github_report_digest'):
            return
        try:
            self.request('/git/ref/heads/'+BRANCH)
        except GitHubError as exc:
            if exc.code!='404': raise
            head=self.request('/git/ref/heads/main')['object']['sha']
            try:
                self.request('/git/refs','POST',{'ref':'refs/heads/'+BRANCH,'sha':head})
            except GitHubError as error:
                if error.code!='422': raise
                self.request('/git/ref/heads/'+BRANCH)
        path='/contents/'+REPORT_PATH
        try:
            current=self.request(path+'?ref='+BRANCH)
            sha=current['sha']
        except GitHubError as exc:
            if exc.code!='404': raise
            sha=None
        data={'message':'Update Oracle runtime delivery report','branch':BRANCH,
              'content':base64.b64encode(encoded.encode()).decode('ascii')}
        if sha: data['sha']=sha
        result=self.request(path,'PUT',data)
        self.store.set('github_report_digest',digest)
        self.store.set('github_report_status',{'status':'synced','checked_at':now_kst().isoformat(timespec='seconds'),
                                             'commit':result.get('commit',{}).get('sha')})

    def tick(self):
        if time.monotonic()<self.next_check: return
        self.next_check=time.monotonic()+300
        if not self.token:
            self.store.set('github_report_status',{'status':'credential_required'})
            return
        try:
            self.publish(snapshot(self.store))
        except Exception as exc:
            code=exc.code if isinstance(exc,GitHubError) else type(exc).__name__
            self.store.set('github_report_status',{'status':'failed','error_code':code,
                                                 'checked_at':now_kst().isoformat(timespec='seconds')})
            LOG.warning('Runtime report sync failed: %s',code)