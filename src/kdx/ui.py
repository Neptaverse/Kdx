from __future__ import annotations

import os
import shutil
import sys
import textwrap
from pathlib import Path
from typing import TextIO

KDX_ASCII_LOGO = """\
                                                *+++                                                
                                              *+++++++                                              
                                            *+++#%%#+++*                                            
                                           +++*%@@@@%*+++*                                          
                                         +++*%@@@@@@@@%*+++                                         
                                       +++*#@@@@@@@@@@@@%*+++                                       
                                     ++++#%@@@@@@@@@@@@@@%#*++*                                     
                                   *+++#%@@@@@@@@@@@@@@@@@@%#*++*                                   
                                 *+++*%@%#%@@@@@@@@@@@@@@%%%@%#+++*                                 
                                +++*%@@#+=+%@@@@@@@@@@@@%*+*%@@%*+++                                
                               ++*%@@@@#==+#@@@@@@@@@@@%*++*#@@@@%*+*                               
                               ++#@@@@@%+=*%@@@@@@@@@%#++++#%@@@@@#+*                               
                               ++#@@@@@%*+*%@@@@@@@@%*+++#%@@@@@@@#+*                               
                               ++#@@@@@%*+*%@@@@@@%#+++*%@@@@@@@@@#+*                               
                               *+#@@@@@%*+*%@@@@@%*+++#%@@@@@@@@@@#+*                               
                               *+#@@@@@%*+*%@@@%#+++*%@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+*%@@#*+++#%@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+*%%*+++*%@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+*#*++*#%@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%=:=+++*%@@@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@%+. .-*#@@@@@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@%=  .=%@@@@@@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@+. .-*#@@@@@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%=:=+++*%@@@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+*#*++*#%@@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+#%%#+++*%@@@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+#%@@#*++*#%@@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+#%@@@%#+++*%@@@@@@@@@@@@#+*                               
                               *+#@@@@@%*+#%@@@@@%*+++#%@@@@@@@@@@#+*                               
                               *++#%@@@%*+#%@@@@@@%#+++*%@@@@@@@%#*+*                               
                               @%*+*#%@%*+#%@@@@@@@@%*+++#%@@@%#*+*%@                               
                                @@%*+*##*+*%@@@@@@@@@%#++++#%#*+*%@@                                
                                  @@#*++++*%@@@@@@@@@@@%*+++++*#@@                                  
                                   @@@#+++*%@@@@@@@@@@@@%*++*#@@@                                   
                                     @@%*++*%@@@@@@@@@@%*++*%@@                                     
                                       @@%*++#%@@@@@@%#++*%@@                                       
                                        @@@%*+*#%@@%#*+*#@@@                                        
                                          @@@#*+*##*++#@@@                                          
                                            @@@#++++#@@@                                            
                                              @@%**%@@                                              
                                                @@@@                                                """

_BANNER_COLOR = "\033[38;5;39m"
_SUCCESS_COLOR = "\033[38;5;78m"
_WARNING_COLOR = "\033[38;5;196m"
_INFO_COLOR = "\033[38;5;250m"
_RESET_COLOR = "\033[0m"
_TRUTHY = {"1", "true", "yes", "on"}
_COMPACT_BANNER = "\n".join(
    [
        "+-----+",
        "| KDX |",
        "+-----+",
    ]
)
_MIN_WIDTH = 24
_MIN_HEIGHT = 6
_FULL_BANNER_WIDTH = max(len(line) for line in KDX_ASCII_LOGO.splitlines())
_FULL_BANNER_HEIGHT = len(KDX_ASCII_LOGO.splitlines())
_COMPACT_BANNER_WIDTH = max(len(line) for line in _COMPACT_BANNER.splitlines())
_COMPACT_BANNER_HEIGHT = len(_COMPACT_BANNER.splitlines())


def _env_flag(name: str, environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(name, "").strip().lower() in _TRUTHY


def should_render_banner(
    *,
    exec_mode: bool,
    stdin_is_tty: bool | None = None,
    stdout_is_tty: bool | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    if exec_mode:
        return False
    if _env_flag("KDX_NO_BANNER", environ):
        return False
    if _env_flag("KDX_FORCE_BANNER", environ):
        return True
    in_tty = sys.stdin.isatty() if stdin_is_tty is None else stdin_is_tty
    out_tty = sys.stdout.isatty() if stdout_is_tty is None else stdout_is_tty
    return bool(in_tty and out_tty)


def _should_colorize(stream: TextIO, environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    mode = env.get("KDX_COLOR", "always").strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    if env.get("NO_COLOR"):
        return False
    if env.get("TERM", "").strip().lower() == "dumb":
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _terminal_size(
    stream: TextIO,
    *,
    environ: dict[str, str] | None = None,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> tuple[int, int]:
    width = max(_MIN_WIDTH, terminal_width) if terminal_width is not None else 0
    height = max(_MIN_HEIGHT, terminal_height) if terminal_height is not None else 0
    if width and height:
        return width, height
    env = os.environ if environ is None else environ
    raw_columns = env.get("COLUMNS", "").strip() if not width else ""
    raw_lines = env.get("LINES", "").strip() if not height else ""
    if raw_columns.isdigit():
        width = max(_MIN_WIDTH, int(raw_columns))
    if raw_lines.isdigit():
        height = max(_MIN_HEIGHT, int(raw_lines))
    if width and height:
        return width, height
    try:
        size = shutil.get_terminal_size(fallback=(120, 40))
        width = width or max(_MIN_WIDTH, size.columns)
        height = height or max(_MIN_HEIGHT, size.lines)
        return width, height
    except OSError:
        return width or 120, height or 40


def _banner_style(
    *,
    width: int,
    height: int,
    environ: dict[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    override = env.get("KDX_BANNER_STYLE", "auto").strip().lower()
    if override in {"off", "none", "0"}:
        return "off"
    if override in {"compact", "small", "minimal"}:
        return "compact"
    if override == "full":
        return "full"
    if _env_flag("KDX_FORCE_BANNER", env):
        if width >= _FULL_BANNER_WIDTH and height >= _FULL_BANNER_HEIGHT + 8:
            return "full"
        return "compact"
    if width >= _FULL_BANNER_WIDTH and height >= _FULL_BANNER_HEIGHT + 8:
        return "full"
    if width >= _COMPACT_BANNER_WIDTH and height >= _COMPACT_BANNER_HEIGHT + 5:
        return "compact"
    return "off"


def _wrap_text(text: str, width: int) -> list[str]:
    wrapped: list[str] = []
    for raw_line in text.splitlines() or [""]:
        if not raw_line:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                raw_line,
                width=max(_MIN_WIDTH, width),
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped


def render_banner(
    *,
    color: bool = False,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    width, height = _terminal_size(
        sys.stderr,
        environ=environ,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )
    style = _banner_style(width=width, height=height, environ=environ)
    if style == "off":
        return ""
    banner = KDX_ASCII_LOGO if style == "full" else _COMPACT_BANNER
    if not color:
        return banner
    return f"{_BANNER_COLOR}{banner}{_RESET_COLOR}"


def _paint(text: str, color_code: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color_code}{text}{_RESET_COLOR}"


def _paint_wrapped(text: str, color_code: str, *, enabled: bool, width: int) -> list[str]:
    return [_paint(line, color_code, enabled=enabled) for line in _wrap_text(text, width)]


def render_startup_status(
    repo_root: Path,
    *,
    file_count: int | None,
    keiro_configured: bool,
    color: bool,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> str:
    width = max(_MIN_WIDTH, terminal_width or 120)
    height = max(_MIN_HEIGHT, terminal_height or 40)
    lines: list[str] = []
    lines.extend(
        _paint_wrapped(
            f"KDX workspace: {repo_root.name}",
            _INFO_COLOR,
            enabled=color,
            width=width,
        )
    )
    lines.extend(
        _paint_wrapped(
            f"Files: {file_count if file_count is not None else 'unknown'} | auto-init: on",
            _INFO_COLOR,
            enabled=color,
            width=width,
        )
    )
    if keiro_configured:
        lines.extend(_paint_wrapped("KEIRO: ready", _SUCCESS_COLOR, enabled=color, width=width))
    else:
        lines.extend(_paint_wrapped("KEIRO: not configured", _WARNING_COLOR, enabled=color, width=width))
        if height >= 9:
            lines.extend(_paint_wrapped("Run: kdx /keiro <api-key>", _WARNING_COLOR, enabled=color, width=width))
        if width >= 44 and height >= 12:
            lines.extend(_paint_wrapped("Get a key: https://www.keirolabs.cloud", _WARNING_COLOR, enabled=color, width=width))
    return "\n".join(lines)


def _normalize_update_notice(update_notice: str, *, width: int, height: int) -> str:
    compact = " ".join(update_notice.split())
    if not compact:
        return ""
    if width < 70 or height < 12:
        if "installed automatically" in compact.lower():
            return "UPDATE: new update installed automatically."
        if "update:" in compact.lower():
            return "UPDATE: new update available | run `kdx update`"
    return compact


def print_banner(
    stream: TextIO | None = None,
    *,
    environ: dict[str, str] | None = None,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> None:
    target = stream or sys.stderr
    width, height = _terminal_size(
        target,
        environ=environ,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )
    banner = render_banner(
        color=_should_colorize(target, environ=environ),
        terminal_width=width,
        terminal_height=height,
        environ=environ,
    )
    if not banner:
        return
    target.write("\n")
    target.write(banner)
    target.write("\n\n")
    target.flush()


def print_launch_panel(
    repo_root: Path,
    *,
    file_count: int | None,
    keiro_configured: bool,
    update_notice: str = "",
    stream: TextIO | None = None,
    environ: dict[str, str] | None = None,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> None:
    target = stream or sys.stderr
    color = _should_colorize(target, environ=environ)
    width, height = _terminal_size(
        target,
        environ=environ,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )
    print_banner(target, environ=environ, terminal_width=width, terminal_height=height)
    target.write(
        render_startup_status(
            repo_root,
            file_count=file_count,
            keiro_configured=keiro_configured,
            color=color,
            terminal_width=width,
            terminal_height=height,
        )
    )
    if update_notice:
        target.write("\n")
        target.write(
            "\n".join(
                _paint_wrapped(
                    _normalize_update_notice(update_notice, width=width, height=height),
                    _WARNING_COLOR,
                    enabled=color,
                    width=width,
                )
            )
        )
    target.write("\n\n")
    target.flush()
