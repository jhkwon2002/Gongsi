"""Install root-owned automatic update assets from an SSH payload or a verified release."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile

FILES={
    '/usr/local/libexec/gongsi-autodeploy.py':'deploy/autodeploy.py',
    '/etc/systemd/system/gongsi-update.service':'deploy/gongsi-update.service',
    '/etc/systemd/system/gongsi-update.timer':'deploy/gongsi-update.timer',
}


def install_assets(assets):
    if set(assets) != set(FILES):
        raise ValueError('Unexpected automatic deployment asset paths')
    for name,content in assets.items():
        if not isinstance(content,str) or len(content) > 128*1024:
            raise ValueError('Invalid automatic deployment asset')
        path=Path(name)
        if path.is_symlink():
            raise ValueError('Refusing a symbolic link at managed asset path')
        if path.exists():
            existing=path.stat()
            if not stat.S_ISREG(existing.st_mode) or existing.st_uid != 0 or existing.st_mode & 0o022:
                raise ValueError('Existing automatic deployment asset must be a protected root-owned file')
            old=path.read_text(encoding='utf-8')
            if name.endswith(('.service','.timer')) and '# Managed by Gongsi' not in old:
                raise ValueError('Preserving an unmanaged systemd unit')
    for name,content in assets.items():
        path=Path(name)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=str(path.parent),delete=False) as output:
            output.write(content.lstrip('\ufeff'))
            temporary=Path(output.name)
        temporary.chmod(0o644)
        os.replace(temporary,path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-release',type=Path)
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run automatic deployment setup as root')
    if Path('/etc/gongsi/source-mode').read_text().strip() != 'archive':
        raise ValueError('Existing archive deployment is required')
    if not Path('/usr/local/sbin/deploy-gongsi').is_file():
        raise ValueError('Existing deployment helper is required')
    for directory,mode in (('/usr/local/libexec',0o755),('/var/lib/gongsi-updates',0o700),('/var/backups/gongsi',0o700)):
        path=Path(directory)
        path.mkdir(parents=True,exist_ok=True)
        if path.is_symlink() or path.stat().st_uid != 0:
            raise ValueError('Managed directory must be root-owned')
        path.chmod(mode)
    release=args.from_release
    if release:
        release=release.resolve()
        if release.stat().st_uid != 0 or release.stat().st_mode & 0o022:
            raise ValueError('Operator source must be a protected root-owned release')
        assets={name:(release/relative).read_text(encoding='utf-8') for name,relative in FILES.items()}
    else:
        assets=globals().get('ASSETS')
        if not isinstance(assets,dict):
            raise ValueError('Missing automatic deployment asset payload')
    install_assets(assets)
    marker=Path('/etc/gongsi/autodeploy-enabled')
    if marker.is_symlink():
        raise ValueError('Refusing a symbolic link at automatic deployment marker')
    marker.write_text('enabled\n',encoding='ascii')
    marker.chmod(0o600)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','gongsi-update.timer'],check=True)
    if release:
        target=(release/'RELEASE').read_text(encoding='ascii').strip()
        operator=Path('/etc/gongsi/autodeploy-release')
        if operator.is_symlink():
            raise ValueError('Refusing a symbolic link at operator version marker')
        operator.write_text(target+'\n',encoding='ascii')
        operator.chmod(0o600)
    if not args.refresh:
        print('Timer installed. Checking the latest tested GitHub commit now; this may take a few minutes.',flush=True)
        subprocess.run(['systemctl','start','gongsi-update.service'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','gongsi-update.timer'],check=True)
        print('AUTO DEPLOY ENABLED: Oracle checks successful GitHub main builds every 3 minutes.',flush=True)
        status=Path('/var/lib/gongsi-updates/status.json')
        if status.is_file():
            print(status.read_text(encoding='utf-8').strip(),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        safe=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        print('AUTO DEPLOY SETUP FAILED: '+safe,flush=True)
        raise SystemExit(1)
