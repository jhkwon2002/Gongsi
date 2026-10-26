"""Download a bounded, validated public GitHub release without git or pip (Python 3.9+)."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPOSITORY = 'jhkwon2002/Gongsi'
API = 'https://api.github.com/repos/' + REPOSITORY
BASE = Path('/opt/gongsi')
REQUIRED = ('gongsi/__main__.py', 'deploy/bootstrap.sh', 'deploy/deploy.sh',
            'deploy/fetch-release.py', 'deploy/configure.py', 'deploy/gongsi.service', '.env.example')
MAX_DOWNLOAD = 4 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024


def read_url(url, limit=MAX_DOWNLOAD):
    request = urllib.request.Request(url, headers={'User-Agent': 'GongsiDeploy/1.0',
                                                 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('GitHub response exceeds the allowed size')
    return data


def valid_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('A full commit SHA is required')
    return value


def main_sha():
    data = json.loads(read_url(API + '/git/ref/heads/main'))
    return valid_sha(data['object']['sha'])


def verify_main_history(sha, head):
    valid_sha(sha)
    valid_sha(head)
    if sha != head:
        data = json.loads(read_url(API + '/compare/' + sha + '...' + head + '?per_page=1'))
        if data.get('status') not in ('ahead', 'identical'):
            raise ValueError('Requested commit is not an ancestor of main')


def extract_archive(data, destination, sha):
    """Only regular files/directories under the exact commit prefix are accepted."""
    valid_sha(sha)
    destination = Path(destination)
    prefix = 'Gongsi-' + sha
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = []
        expanded = 0
        for member in archive:
            expanded += max(0, member.size)
            members.append(member)
            if len(members) > 512 or expanded > MAX_EXPANDED:
                raise ValueError('Source archive exceeds the allowed size')
        selected = []
        seen = set()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != prefix or '..' in parts or '\\' in member.name
                    or not (member.isdir() or member.isfile()) or member.size < 0):
                raise ValueError('Unsafe source archive member')
            relative = Path(*parts[1:])
            if len(parts) == 1:
                if not member.isdir():
                    raise ValueError('Invalid archive root')
                continue
            if relative in seen:
                raise ValueError('Duplicate source archive path')
            seen.add(relative)
            selected.append((member, relative))
        for member, relative in selected:
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=64 * 1024)
                target.chmod(0o755 if relative.suffix == '.sh' else 0o644)
    if not all((destination / path).is_file() for path in REQUIRED):
        raise ValueError('Source archive is missing required project files')
    with (destination / 'RELEASE').open('x', encoding='ascii') as output:
        output.write(sha + '\n')


def fetch_release(sha):
    releases = BASE / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / valid_sha(sha)
    if release.exists() or release.is_symlink():
        if (release.is_symlink() or not release.is_dir() or release.stat().st_uid != 0
                or release.stat().st_mode & 0o022
                or not (release / 'RELEASE').is_file()
                or (release / 'RELEASE').read_text(encoding='ascii').strip() != sha
                or not all((release / p).is_file() for p in REQUIRED)):
            raise ValueError('Existing release is not a verified project directory; preserving it')
        return release
    stage = Path(tempfile.mkdtemp(prefix='archive-stage.', dir=str(releases)))
    try:
        print('[server] Downloading the exact GitHub commit archive', flush=True)
        data = read_url('https://codeload.github.com/' + REPOSITORY + '/tar.gz/' + sha)
        extract_archive(data, stage, sha)
        stage.chmod(0o755)
        stage.rename(release)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return release


def main(arguments=None):
    import fcntl
    arguments = sys.argv[1:] if arguments is None else arguments
    if os.geteuid() != 0 or len(arguments) != 1:
        raise ValueError('Run as root with --bootstrap or one full commit SHA')
    bootstrap = arguments[0] == '--bootstrap'
    requested = None if bootstrap else valid_sha(arguments[0])
    with open('/run/lock/gongsi-archive.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        head = main_sha()
        sha = head if bootstrap else requested
        verify_main_history(sha, head)
        release = fetch_release(sha)
        if bootstrap:
            subprocess.run(['bash', str(release / 'deploy/bootstrap.sh'), '--archive'], check=True)
            marker = BASE / 'bootstrap-release'
            if marker.is_symlink():
                raise ValueError('Refusing symbolic link at bootstrap marker')
            with tempfile.NamedTemporaryFile(mode='w', encoding='ascii', dir=str(BASE), delete=False) as output:
                output.write(sha + '\n')
                temporary = Path(output.name)
            os.replace(temporary, marker)
            print('SERVER BOOTSTRAP OK: archive source; no Git or Python installation', flush=True)
        else:
            print('SOURCE READY ' + sha, flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Archive preparation failed: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        raise SystemExit(1)
