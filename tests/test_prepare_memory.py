"""Run the real memory guard against a disposable filesystem and mocked system tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Linux shell integration')
class MemoryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.mem = self.root / 'meminfo'
        self.mem.write_text('MemTotal: 510000 kB\nSwapTotal: 510000 kB\n')
        self.fstab = self.root / 'fstab'
        self.fstab.write_text('# existing system entries\n')
        self.swap_dir = self.root / 'swap'
        self.swap = self.swap_dir / 'swapfile'
        self.active = self.root / 'active'
        source = (Path(__file__).resolve().parents[1] / 'deploy/prepare-memory.sh').read_text()
        # Only privilege and fixed paths change. All safety/control flow is the production script.
        source = source.replace('[[ $EUID == 0 ]]', '[[ 1 == 1 ]]')
        replacements = {
            '/run/lock/gongsi-memory.lock': str(self.root / 'memory.lock'),
            '/proc/meminfo': str(self.mem),
            '/var/lib/gongsi-swap': str(self.swap_dir),
            '/etc/fstab': str(self.fstab),
        }
        for old, new in replacements.items():
            source = source.replace(old, new)
        self.script = self.root / 'prepare.sh'
        self.script.write_text(source)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        MOCK_MEM=str(self.mem), MOCK_SWAP=str(self.swap),
                        MOCK_ACTIVE=str(self.active), MOCK_ROOT=str(self.root))
        self.mock('install', 'mkdir -p "$MOCK_ROOT/swap"; chmod 700 "$MOCK_ROOT/swap"')
        self.mock('pgrep', 'exit "${MOCK_PGREP_EXIT:-1}"')
        self.mock('findmnt', 'echo "${MOCK_FS:-ext4}"')
        self.mock('df', 'printf "Filesystem 1024-blocks Used Available Capacity Mounted\nmock 9000000 1000000 %s 10%% /\n" "${MOCK_DISK_KB:-8000000}"')
        stat_path = shutil.which('stat')
        self.mock('stat', '"' + stat_path + '" "$@" | sed "s/^$(id -u):/0:/"')
        self.mock('dd', 'truncate -s 3221225472 "$MOCK_SWAP"')
        self.mock('mkswap', 'touch "$MOCK_ROOT/initialized"')
        self.mock('blkid', '[ -f "$MOCK_ROOT/initialized" ] && echo swap')
        self.mock('swapon', '''if [ "${1:-}" = "--show=NAME" ]; then
  [ ! -f "$MOCK_ACTIVE" ] || echo "$MOCK_SWAP"
else
  touch "$MOCK_ACTIVE"
  sed -i 's/^SwapTotal:.*/SwapTotal: 3655724 kB/' "$MOCK_MEM"
fi''')
        self.mock('free', 'cat "$MOCK_MEM"')
        self.mock('systemctl', 'echo "$*" > "$MOCK_ROOT/systemctl-call"')

    def mock(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\nset -e\n' + body + '\n')
        path.chmod(0o755)

    def run_guard(self, **env):
        return subprocess.run(['bash', str(self.script)], env=dict(self.env, **env),
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)

    def test_enough_memory_makes_no_swap(self):
        self.mem.write_text('MemTotal: 4194304 kB\nSwapTotal: 0 kB\n')
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.swap.exists())
        self.assertEqual(self.fstab.read_text(), '# existing system entries\n')

    def test_active_package_manager_blocks_changes(self):
        result = self.run_guard(MOCK_PGREP_EXIT='0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('still running', result.stdout)
        self.assertFalse(self.swap_dir.exists())

    def test_low_disk_blocks_allocation(self):
        result = self.run_guard(MOCK_DISK_KB='1000000')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.swap.exists())
        self.assertFalse(self.active.exists())

    def test_unknown_existing_file_is_preserved(self):
        self.swap_dir.mkdir(mode=0o700)
        self.swap.write_text('preserve me')
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.swap.read_text(), 'preserve me')
        self.assertFalse(self.active.exists())

    def test_unsupported_filesystem_blocks_allocation(self):
        result = self.run_guard(MOCK_FS='btrfs')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.swap.exists())

    def test_create_activate_persist_and_repeat_without_duplicates(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.swap.stat().st_size, 3221225472)
        self.assertEqual(self.swap.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.active.exists())
        self.assertEqual(len(list(self.root.glob('fstab.gongsi-backup.*'))), 1)
        first_fstab = self.fstab.read_text()
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.fstab.read_text(), first_fstab)
        self.assertEqual((self.root / 'systemctl-call').read_text().strip(), 'daemon-reload')

    def test_recover_activation_before_fstab_write(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.fstab.write_text('# existing system entries\n')
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(self.swap) + ' none swap defaults,nofail 0 0', self.fstab.read_text())
