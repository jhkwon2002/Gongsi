"""Inspect the running bot and optionally send one explicitly labelled test message."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

PROJECT = Path('/opt/gongsi/current')
if PROJECT.is_dir():
    sys.path.insert(0, str(PROJECT))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gongsi.api import ApiError, Telegram, now_kst, request_json
from urllib.parse import urlencode

OWNER = 6766930417
BOT_USERNAME = 'auto_dart_gongsi_bot'


def read_state(path):
    # Read-only URI avoids creating or changing state alongside the running worker.
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5) as database:
        rows = dict(database.execute('SELECT key, value FROM kv'))
    return {key: json.loads(rows[key]) for key in
            ('settings', 'last_scan_success', 'last_scan_error', 'release', 'poll_seconds') if key in rows}


def scan_age_seconds(value, now):
    try:
        previous = datetime.fromisoformat(value)
        if previous.tzinfo is None:
            return None
        age = (now - previous).total_seconds()
        return round(age, 1) if age >= 0 else None
    except (TypeError, ValueError):
        return None


def run_checks(config, state, service_active, send_test=False):
    if int(config.get('TELEGRAM_OWNER_ID', '0')) != OWNER:
        raise ValueError('Unexpected Telegram recipient; test will not be sent')
    token = config.get('TELEGRAM_BOT_TOKEN', '')
    key = config.get('DART_API_KEY', '')
    if not token or not key:
        raise ValueError('Server API configuration is incomplete')
    now = now_kst()
    preferences = state.get('settings', {})
    interval = int(state.get('poll_seconds', 300))
    age = scan_age_seconds(state.get('last_scan_success'), now)
    result = {
        'service_active': bool(service_active),
        'build': state.get('release', 'unknown'),
        'poll_seconds': interval,
        'paused': bool(preferences.get('paused', False)),
        'selected_report_count': len(preferences.get('selected', [])),
        'last_scan_success': state.get('last_scan_success'),
        'last_scan_error': state.get('last_scan_error', ''),
        'last_scan_age_seconds': age,
        'scan_fresh': age is not None and age <= interval * 2 + 60,
        'dart_api_ok': False,
        'telegram_identity_ok': False,
        'telegram_test_sent': False,
    }
    day = now.strftime('%Y%m%d')
    try:
        sample = request_json('OpenDART', 'https://opendart.fss.or.kr/api/list.json?' + urlencode(
            {'crtfc_key': key, 'bgn_de': day, 'end_de': day, 'page_count': 1}), timeout=15)
        result['dart_api_status'] = str(sample.get('status', 'invalid'))
        result['dart_api_ok'] = result['dart_api_status'] in ('000', '013')
    except Exception as exc:
        result['dart_api_status'] = exc.code if isinstance(exc, ApiError) else type(exc).__name__
    tg = Telegram(token)
    try:
        identity = tg.call('getMe')
        result['telegram_identity_ok'] = identity.get('username') == BOT_USERNAME
        if not result['telegram_identity_ok']:
            raise ValueError('Unexpected Telegram bot; test will not be sent')
        if send_test:
            label = lambda passed: '정상' if passed else '확인 필요'
            text = ('[테스트 알림] 공시 봇 연결 점검\n'
                    + '시간: ' + now.isoformat(timespec='seconds')
                    + '\n서버 서비스: ' + label(result['service_active'])
                    + '\nDART API 연결: ' + label(result['dart_api_ok'])
                    + '\n최근 자동 조회: ' + label(result['scan_fresh'] and not result['last_scan_error'])
                    + '\n선택한 보고서: ' + str(result['selected_report_count']) + '개'
                    + '\n실제 신규 공시가 아닌 수신 확인용 메시지입니다.')
            sent = tg.call('sendMessage', chat_id=OWNER, text=text)
            result['telegram_test_sent'] = bool(sent.get('message_id'))
    except ValueError:
        raise
    except Exception as exc:
        result['telegram_error'] = exc.code if isinstance(exc, ApiError) else type(exc).__name__
    result['health_ok'] = (result['service_active'] and result['dart_api_ok']
                           and result['telegram_identity_ok'] and result['scan_fresh']
                           and not result['last_scan_error']
                           and (not send_test or result['telegram_test_sent']))
    result['monitoring_ready'] = (result['health_ok'] and not result['paused']
                                  and result['selected_report_count'] > 0)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send-test', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run as root to read the existing server configuration')
    config = {}
    for line in Path('/etc/gongsi/gongsi.env').read_text(encoding='utf-8').splitlines():
        name, separator, value = line.partition('=')
        if separator and not name.startswith('#'):
            config[name] = value
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'gongsi.service']).returncode == 0
    import pwd
    account = pwd.getpwnam('gongsi')
    os.initgroups('gongsi', account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    state = read_state('/var/lib/gongsi/store.db')
    result = run_checks(config, state, active, args.send_test)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    print('HEALTH TEST PASS' if result['health_ok'] else 'HEALTH TEST NEEDS ATTENTION')
    if not result['monitoring_ready']:
        print('Check report selection, pause state and recent scan status in Telegram /status.')
    return 0 if result['health_ok'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        safe = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print('HEALTH TEST FAILED: ' + safe, file=sys.stderr)
        raise SystemExit(1)
