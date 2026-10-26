import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('gongsi_fetch_release', Path(__file__).resolve().parents[1] / 'deploy/fetch-release.py')
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
SHA = 'a' * 40
HEAD = 'b' * 40


def archive_bytes(extra=None, missing=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name in fetch.REQUIRED:
            if name == missing:
                continue
            info = tarfile.TarInfo('Gongsi-' + SHA + '/' + name)
            content = b'# test file\n'
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if extra:
            info, content = extra
            archive.addfile(info, io.BytesIO(content) if content is not None else None)
    return output.getvalue()


class ArchiveSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'release'
        self.target.mkdir()

    def test_source_extracts_with_exact_commit_marker(self):
        fetch.extract_archive(archive_bytes(), self.target, SHA)
        self.assertEqual((self.target / 'RELEASE').read_text(), SHA + '\n')
        self.assertTrue((self.target / 'gongsi/__main__.py').is_file())

    def test_traversal_is_rejected_before_writing_files(self):
        info = tarfile.TarInfo('Gongsi-' + SHA + '/../outside')
        info.size = 1
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            fetch.extract_archive(archive_bytes((info, b'x')), self.target, SHA)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse((self.root / 'outside').exists())

    def test_symlinks_are_rejected(self):
        info = tarfile.TarInfo('Gongsi-' + SHA + '/link')
        info.type = tarfile.SYMTYPE
        info.linkname = '/etc/passwd'
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            fetch.extract_archive(archive_bytes((info, None)), self.target, SHA)

    def test_duplicate_paths_are_rejected(self):
        info = tarfile.TarInfo('Gongsi-' + SHA + '/deploy/bootstrap.sh')
        info.size = 1
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            fetch.extract_archive(archive_bytes((info, b'x')), self.target, SHA)

    def test_expansion_size_is_bounded(self):
        with patch.object(fetch, 'MAX_EXPANDED', 1):
            with self.assertRaisesRegex(ValueError, 'size'):
                fetch.extract_archive(archive_bytes(), self.target, SHA)

    def test_missing_required_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            fetch.extract_archive(archive_bytes(missing='gongsi/__main__.py'), self.target, SHA)

    def test_unrelated_commit_cannot_be_deployed(self):
        with patch.object(fetch, 'read_url', return_value=json.dumps({'status': 'diverged'}).encode()):
            with self.assertRaisesRegex(ValueError, 'ancestor'):
                fetch.verify_main_history(SHA, HEAD)

    def test_ancestor_is_accepted(self):
        with patch.object(fetch, 'read_url', return_value=b'{"status":"ahead"}') as request:
            fetch.verify_main_history(SHA, HEAD)
            self.assertIn(SHA + '...' + HEAD, request.call_args[0][0])

    def test_branch_names_cannot_replace_full_sha(self):
        with self.assertRaisesRegex(ValueError, 'SHA'):
            fetch.verify_main_history('main', HEAD)

    def test_current_head_needs_no_compare_request(self):
        with patch.object(fetch, 'read_url') as request:
            fetch.verify_main_history(SHA, SHA)
            request.assert_not_called()

    def test_failed_download_preserves_existing_releases(self):
        with patch.object(fetch, 'BASE', self.root), patch.object(fetch, 'read_url', side_effect=OSError):
            releases = self.root / 'releases'
            releases.mkdir()
            old = releases / HEAD
            old.mkdir()
            (old / 'keep').write_text('preserve')
            with self.assertRaises(OSError):
                fetch.fetch_release(SHA)
            self.assertEqual((old / 'keep').read_text(), 'preserve')
            self.assertEqual(list(releases.iterdir()), [old])
