from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_render_launcher_content_unix_uses_double_dash_passthrough(self) -> None:
        content = bootstrap._render_launcher_content(
            Path('/usr/bin/python3'),
            Path('/tmp/Kdx/bootstrap.py'),
            platform_name='posix',
        )
        self.assertIn('"/usr/bin/python3" "/tmp/Kdx/bootstrap.py" -- "$@"', content)

    def test_render_launcher_content_windows_uses_cmd_passthrough(self) -> None:
        content = bootstrap._render_launcher_content(
            Path('C:/Python312/python.exe'),
            Path('C:/Kdx/bootstrap.py'),
            platform_name='nt',
        )
        self.assertIn('"C:/Python312/python.exe" "C:/Kdx/bootstrap.py" -- %*', content)

    def test_path_contains_is_case_insensitive_on_windows(self) -> None:
        target = Path('C:/Users/Test/AppData/Roaming/Python/Scripts')
        path_value = 'C:/Windows;C:/USERS/TEST/APPDATA/ROAMING/PYTHON/SCRIPTS'
        self.assertTrue(bootstrap._path_contains(target, path_value, platform_name='nt'))


    def test_main_allows_python_dash_m_passthrough(self) -> None:
        with mock.patch.object(bootstrap, 'ensure_environment', return_value=Path('/tmp/venv-python')):
            with mock.patch.object(bootstrap, 'install_global_launcher', return_value={"status": "unchanged", "launcher_path": "/tmp/kdx", "bin_dir": "/tmp", "on_path": True}):
                with mock.patch.object(bootstrap, 'run') as run_mock:
                    run_mock.return_value.returncode = 0
                    code = bootstrap.main(["--python", "-m", "unittest", "discover"])
        self.assertEqual(code, 0)
        run_mock.assert_called_once()
        command = run_mock.call_args.kwargs.get('command') or run_mock.call_args.args[0]
        self.assertEqual(command, ['/tmp/venv-python', '-m', 'unittest', 'discover'])

    def test_install_global_launcher_writes_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            info = bootstrap.install_global_launcher(
                python_executable=Path('/usr/bin/python3'),
                bootstrap_path=Path('/tmp/Kdx/bootstrap.py'),
                bin_dir=bin_dir,
            )
            launcher = Path(str(info['launcher_path']))
            self.assertTrue(launcher.exists())
            content = launcher.read_text(encoding='utf-8')
            self.assertIn('bootstrap.py', content)
            self.assertEqual(info['status'], 'created')

    def test_python_runtime_guard_rejects_prerelease(self) -> None:
        fake = SimpleNamespace(
            major=3,
            minor=12,
            micro=0,
            releaselevel='candidate',
            serial=1,
        )
        message = bootstrap._python_runtime_guard_error(fake)
        self.assertIn('stable Python release', message)
        self.assertIn('3.12.0rc1', message)

    def test_python_runtime_guard_allows_final_release(self) -> None:
        fake = SimpleNamespace(
            major=3,
            minor=12,
            micro=5,
            releaselevel='final',
            serial=0,
        )
        self.assertEqual(bootstrap._python_runtime_guard_error(fake), '')


if __name__ == '__main__':
    unittest.main()
