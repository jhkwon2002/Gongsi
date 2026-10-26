"""Send up to five current-day, currently selected filings as labelled test replays."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
sys.path.insert(0,'/opt/gongsi/current')
from gongsi.api import Telegram,now_kst
from gongsi.catalog import matches
from gongsi.extraction import Extractor,format_notification
from gongsi.storage import Store


def main():
    config=dict(line.split('=',1) for line in Path('/etc/gongsi/gongsi.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    if config.get('TELEGRAM_OWNER_ID')!='6766930417':
        raise ValueError('Unexpected recipient; nothing sent')
    import pwd
    account=pwd.getpwnam('gongsi')
    os.initgroups('gongsi',account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    today=now_kst().strftime('%Y%m%d')
    reports=[]
    with sqlite3.connect('file:/var/lib/gongsi/store.db?mode=ro',uri=True,timeout=10) as db:
        row=db.execute("SELECT value FROM kv WHERE key='settings'").fetchone()
        selected=json.loads(row[0]).get('selected',[]) if row else []
        for row in db.execute('SELECT data FROM reports ORDER BY receipt DESC'):
            report=json.loads(row[0])
            if report.get('rcept_dt')==today and matches(report.get('report_nm',''),selected):
                reports.append(report)
                if len(reports)==5:
                    break
    if not reports:
        print('NO MATCHING FILINGS TODAY: no messages sent.')
        return
    tg=Telegram(config['TELEGRAM_BOT_TOKEN'])
    if tg.call('getMe').get('username')!='auto_dart_gongsi_bot':
        raise ValueError('Unexpected bot; nothing sent')
    summary_store=Store('/var/lib/gongsi/store.db')
    extractor=Extractor(config['DART_API_KEY'],summary_store,int(config.get('DART_DAILY_LIMIT','18000')))
    for index,report in enumerate(reports,1):
        title=report['report_nm'].strip()
        try:
            summary=extractor.extract(report)
        except Exception:
            summary={'source':'추출 불가 · 원문 확인','fields':[]}
        text=f'[테스트 재전송 {index}/{len(reports)}]\n'+format_notification(report,summary,html=True)+'\n수신 확인용 재전송입니다.'
        result=tg.call('sendMessage',chat_id=6766930417,text=text,parse_mode='HTML',link_preview_options={'is_disabled':True})
        print(json.dumps({'sent':index,'company':report['corp_name'],'title':title,'receipt':report['rcept_no'],'message_id':result.get('message_id')},ensure_ascii=True),flush=True)
        time.sleep(1.3)
    summary_store.close()
    print('TEST REPLAY SENT: '+str(len(reports)),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('TEST REPLAY STOPPED: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
