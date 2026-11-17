"""Installer regression checks; no real package manager or sudo is executed."""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
SCRIPT = BASE / 'install-online.sh'
VERSION = (BASE / 'VERSION').read_text().strip()


def shell(code):
    return subprocess.run(['bash', '-c', 'source ' + shlex.quote(str(SCRIPT)) + '\n' + code], capture_output=True, text=True)


class InstallerTests(unittest.TestCase):
    def test_distribution_packages(self):
        for distribution, manager, package in [
            ('arch', 'pacman', 'libappindicator'),
            ('cachyos arch', 'pacman', 'python-xlib'),
            ('manjaro arch', 'pacman', 'python-cairo'),
            ('ubuntu debian', 'apt-get', 'gir1.2-ayatanaappindicator3-0.1'),
            ('debian', 'apt-get', 'python3-gi-cairo'),
            ('linuxmint ubuntu debian', 'apt-get', 'python3-xlib'),
        ]:
            result = shell('matrix_packages ' + shlex.quote(distribution) + '; printf "%s\\n" "$MATRIX_MANAGER" "${MATRIX_PACKAGES[@]}"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], manager)
            self.assertIn(package, result.stdout.splitlines())
        self.assertNotEqual(shell('matrix_packages unknown-os').returncode, 0)

    def test_apt_update_failure_stops_package_install(self):
        result = shell('''
matrix_packages debian
sudo() { printf 'COMMAND %s\\n' "$*"; return 42; }
if matrix_install_packages; then exit 90; else exit 0; fi
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('COMMAND apt-get update', result.stdout)
        self.assertNotIn('COMMAND apt-get install', result.stdout)

    def test_checksum_rejects_corruption_and_other_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            name = f'matrix-wallpaper-{VERSION}.tar.gz'
            archive = path / name
            checksum = path / (name + '.sha256')
            archive.write_bytes(b'verified archive fixture')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum.write_text(f'{digest}  {name}\n')
            command = 'matrix_verify_archive ' + shlex.quote(directory)
            self.assertEqual(shell(command).returncode, 0)
            archive.write_bytes(b'corrupted')
            self.assertNotEqual(shell(command).returncode, 0)
            checksum.write_text(f'{digest}  ../../other-file\n')
            self.assertNotEqual(shell(command).returncode, 0)
            checksum.write_text('not a checksum\n')
            self.assertNotEqual(shell(command).returncode, 0)

    def test_private_download_uses_gh_without_tokens(self):
        result = shell('''
gh() { printf 'GH %s\\n' "$*"; }
curl() { printf 'UNEXPECTED CURL\\n'; return 99; }
matrix_download /tmp/download-fixture
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'GH release download v{VERSION}', result.stdout)
        self.assertIn(f'--pattern matrix-wallpaper-{VERSION}.tar.gz.sha256', result.stdout)
        self.assertNotIn('UNEXPECTED CURL', result.stdout)

    def test_failed_public_download_does_not_continue(self):
        result = shell('''
gh() { return 1; }
curl() { printf 'CURL CALLED\\n'; return 22; }
matrix_download /tmp/download-fixture
''')
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertEqual(result.stdout.count('CURL CALLED'), 1)

    def test_dry_run_does_not_download_or_install(self):
        result = shell('''
sudo() { printf 'UNEXPECTED SUDO\\n'; return 99; }
gh() { printf 'UNEXPECTED GH\\n'; return 99; }
curl() { printf 'UNEXPECTED CURL\\n'; return 99; }
matrix_main --dry-run
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SHA-256', result.stdout)
        self.assertNotIn('UNEXPECTED', result.stdout)

    @unittest.skipIf(os.geteuid() == 0, 'Real installation rejects root')
    def test_invalid_download_never_reaches_sudo_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'workspace'
            marker = Path(directory) / 'sudo-called'
            code = '''
systemctl() { return 0; }
xfdesktop() { return 0; }
matrix_download() {
    printf '%s' "$1" > RECORD
    printf 'bad archive' > "$1/matrix-wallpaper-${MATRIX_VERSION}.tar.gz"
    printf 'bad checksum\\n' > "$1/matrix-wallpaper-${MATRIX_VERSION}.tar.gz.sha256"
}
matrix_install_packages() { touch MARKER; }
XDG_SESSION_TYPE=x11
matrix_main
'''.replace('RECORD', shlex.quote(str(record))).replace('MARKER', shlex.quote(str(marker)))
            result = shell(code)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertFalse(Path(record.read_text()).exists(), 'Temporary download must be removed on failure')

    def test_indicator_compatibility(self):
        import indicator
        sentinel = object()
        def require(name, version):
            if name == 'AppIndicator3':
                raise ValueError('not installed')
        with patch.object(indicator.gi, 'require_version', side_effect=require), patch.object(indicator.importlib, 'import_module', return_value=sentinel) as imported:
            self.assertIs(indicator.load_indicator(), sentinel)
            imported.assert_called_once_with('gi.repository.AyatanaAppIndicator3')
        with patch.object(indicator.gi, 'require_version', side_effect=ValueError('not installed')):
            with self.assertRaises(ImportError):
                indicator.load_indicator()


if __name__ == '__main__':
    unittest.main(verbosity=2)
