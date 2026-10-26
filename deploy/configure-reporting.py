"""Configure only the outbound reporting credential on the Oracle terminal."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,'/opt/gongsi/current')
from gongsi.runtime_reports import Publisher


def main():
    if os.geteuid()!=0 or not sys.stdin.isatty():
        raise ValueError('Run as root in the interactive Oracle SSH terminal')
    path=Path('/etc/gongsi/gongsi.env')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected existing regular configuration file')
    token=getpass.getpass('GitHub fine-grained token (Gongsi Contents read/write, hidden): ').strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError('Invalid credential format')
    # Validate repository access without printing the credential or HTTP response.
    Publisher(None,token).request('/git/ref/heads/main')
    lines=[line for line in path.read_text(encoding='utf-8').splitlines() if not line.startswith('GITHUB_REPORT_TOKEN=')]
    lines.append('GITHUB_REPORT_TOKEN='+token)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=str(path.parent),delete=False) as output:
        output.write('\n'.join(lines)+'\n')
        temporary=Path(output.name)
    temporary.chmod(0o600)
    os.replace(temporary,path)
    subprocess.run(['systemctl','restart','gongsi.service'],check=True)
    print('Reporting credential saved. Check Telegram /status for the sync result.')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Reporting setup failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)