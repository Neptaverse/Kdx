from __future__ import annotations

import io
from pathlib import Path
import unittest

from kdx.ui import KDX_ASCII_LOGO, print_banner, print_launch_panel, render_banner, should_render_banner


class _FakeStream(io.StringIO):
    def __init__(self, *, is_tty: bool) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


class UiTests(unittest.TestCase):
    def test_should_render_banner_for_interactive_terminal(self) -> None:
        self.assertTrue(should_render_banner(exec_mode=False, stdin_is_tty=True, stdout_is_tty=True, environ={}))

    def test_should_not_render_banner_for_exec_mode(self) -> None:
        self.assertFalse(should_render_banner(exec_mode=True, stdin_is_tty=True, stdout_is_tty=True, environ={}))

    def test_should_not_render_banner_when_disabled(self) -> None:
        self.assertFalse(
            should_render_banner(
                exec_mode=False,
                stdin_is_tty=True,
                stdout_is_tty=True,
                environ={"KDX_NO_BANNER": "1"},
            )
        )

    def test_render_banner_preserves_ascii_art(self) -> None:
        banner = render_banner(color=False)
        self.assertEqual(banner, KDX_ASCII_LOGO)
        self.assertIn("@@@@", banner)
        self.assertNotIn("\033[", banner)

    def test_print_banner_respects_color_policy(self) -> None:
        stream = _FakeStream(is_tty=True)
        print_banner(stream, environ={"KDX_COLOR": "always"})
        output = stream.getvalue()
        self.assertIn("\033[38;5;39m", output)
        self.assertIn("@@@@", output)
        self.assertTrue(output.endswith("\n\n"))

    def test_print_banner_defaults_to_blue_for_interactive_launch(self) -> None:
        stream = _FakeStream(is_tty=True)
        print_banner(stream, environ={})
        self.assertIn("\033[38;5;39m", stream.getvalue())

    def test_launch_panel_warns_when_keiro_missing(self) -> None:
        stream = _FakeStream(is_tty=True)
        print_launch_panel(Path("/tmp/demo"), file_count=42, keiro_configured=False, stream=stream, environ={"KDX_COLOR": "always"})
        output = stream.getvalue()
        self.assertIn("KEIRO: not configured", output)
        self.assertIn("kdx /keiro <api-key>", output)
        self.assertIn("\033[38;5;196m", output)


if __name__ == "__main__":
    unittest.main()
