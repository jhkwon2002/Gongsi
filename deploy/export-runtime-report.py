"""Export the same allowlisted runtime report without exposing credentials."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,'/opt/gongsi/current')
from gongsi.storage import Store
from gongsi.runtime_reports import snapshot

if os.geteuid()!=0:
    raise SystemExit('Run through sudo on Oracle')
import pwd
account=pwd.getpwnam('gongsi')
os.initgroups('gongsi',account.pw_gid)
os.setgid(account.pw_gid)
os.setuid(account.pw_uid)
store=Store('/var/lib/gongsi/store.db')
try:
    print(json.dumps(snapshot(store),ensure_ascii=True,indent=2))
finally:
    store.close()