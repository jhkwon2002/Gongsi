"""Poll public GitHub CI results and deploy only a tested main commit. No credentials needed."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode
import urllib.request

REPO = 'jhkwon2002/Gongsi'
API = 'https://api.github.com/repos/' + REPO
WORKFLOW = '.github/workflows/ci-deploy.yml'
CURRENT = Path('/opt/gongsi/current')
OPERATOR_MARKER = Path('/etc/gongsi/autodeploy-release')
STATUS = Path('/var/lib/gongsi-updates/status.json')


def sha_value(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Invalid GitHub commit SHA')
    return value


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent':'GongsiAutoDeploy/1.0',
                                                  'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError('GitHub metadata response exceeds allowed size')
    return json.loads(content)


def ci_decision(runs, sha):
    """Newest matching push run controls eligibility; an old successful rerun cannot mask failure."""
    matches = [run for run in runs if run.get('head_sha') == sha and run.get('event') == 'push'
               and run.get('head_branch') == 'main' and run.get('path') == WORKFLOW]
    if not matches:
        return 'waiting'
    latest = max(matches, key=lambda run:(int(run.get('run_number',0)),int(run.get('run_attempt',1))))
    if latest.get('status') != 'completed':
        return 'waiting'
    return 'passed' if latest.get('conclusion') == 'success' else 'failed'


def available_memory_kb(path=Path('/proc/meminfo')):
    for line in path.read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1])
    return 0


def write_status(value):
    value['checked_at']=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(STATUS.parent), delete=False) as output:
        json.dump(value,output,ensure_ascii=True)
        output.write('\n')
        temporary=Path(output.name)
    os.replace(temporary,STATUS)
    print(json.dumps(value,ensure_ascii=True),flush=True)


def refresh_operator_tools(release):
    installer=release/'deploy/install-autodeploy.py'
    if not installer.is_file():
        raise ValueError('Release is missing automatic deployment setup')
    subprocess.run(['bash',str(release/'deploy/bootstrap.sh'),'--archive'],check=True)
    subprocess.run([sys.executable,str(installer),'--from-release',str(release),'--refresh'],check=True)


def update_once():
    current=sha_value((CURRENT/'RELEASE').read_text(encoding='ascii').strip())
    head=sha_value(get_json(API+'/git/ref/heads/main')['object']['sha'])
    result={'current':current,'target':head}
    operator=OPERATOR_MARKER.read_text(encoding='ascii').strip() if OPERATOR_MARKER.exists() else ''
    needs_refresh=operator != current and (CURRENT/'deploy/install-autodeploy.py').is_file()
    if current == head and not needs_refresh:
        result['result']='unchanged'
        return result
    query=urlencode({'branch':'main','event':'push','head_sha':head,'per_page':5})
    runs=get_json(API+'/actions/workflows/ci-deploy.yml/runs?'+query).get('workflow_runs',[])
    decision=ci_decision(runs,head)
    result['ci']=decision
    if decision != 'passed':
        result['result']='deferred_ci_'+decision
        return result
    if available_memory_kb() < 96*1024:
        result['result']='deferred_low_memory'
        return result
    # Re-read main after CI lookup: never deploy a superseded head by accident.
    if sha_value(get_json(API+'/git/ref/heads/main')['object']['sha']) != head:
        result['result']='deferred_main_changed'
        return result
    if current != head:
        subprocess.run(['/usr/local/sbin/deploy-gongsi',head],check=True)
    deployed=sha_value((CURRENT/'RELEASE').read_text(encoding='ascii').strip())
    if deployed != head:
        raise ValueError('Deployment did not activate the requested commit')
    refresh_operator_tools(CURRENT.resolve())
    result.update(current=deployed,result='deployed' if current != head else 'operator_refreshed')
    return result


def main():
    import fcntl
    if os.geteuid() != 0:
        raise ValueError('Run the update service as root')
    if Path('/etc/gongsi/source-mode').read_text().strip() != 'archive':
        raise ValueError('Automatic polling requires archive source mode')
    with open('/run/lock/gongsi-update.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Update already running',flush=True)
            return
        write_status(update_once())


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        write_status({'result':'error','error_type':type(exc).__name__})
        raise SystemExit(1)
