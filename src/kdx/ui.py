from __future__ import annotations

import os
import sys
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


def render_banner(*, color: bool = False) -> str:
    if not color:
        return KDX_ASCII_LOGO
    return f"{_BANNER_COLOR}{KDX_ASCII_LOGO}{_RESET_COLOR}"


def _paint(text: str, color_code: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color_code}{text}{_RESET_COLOR}"


def render_startup_status(repo_root: Path, *, file_count: int | None, keiro_configured: bool, color: bool) -> str:
    repo_line = _paint(
        f"KDX workspace: {repo_root.name} | indexed files: {file_count if file_count is not None else 'unknown'} | auto-init: on",
        _INFO_COLOR,
        enabled=color,
    )
    if keiro_configured:
        keiro_line = _paint("KEIRO: ready", _SUCCESS_COLOR, enabled=color)
    else:
        keiro_line = _paint(
            "KEIRO: not configured | get a key at https://www.keirolabs.cloud and run `kdx /keiro <api-key>`",
            _WARNING_COLOR,
            enabled=color,
        )
    return "\n".join([repo_line, keiro_line])


def print_banner(stream: TextIO | None = None, *, environ: dict[str, str] | None = None) -> None:
    target = stream or sys.stderr
    target.write("\n")
    target.write(render_banner(color=_should_colorize(target, environ=environ)))
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
) -> None:
    target = stream or sys.stderr
    color = _should_colorize(target, environ=environ)
    print_banner(target, environ=environ)
    target.write(render_startup_status(repo_root, file_count=file_count, keiro_configured=keiro_configured, color=color))
    if update_notice:
        target.write("\n")
        target.write(_paint(update_notice, _WARNING_COLOR, enabled=color))
    target.write("\n\n")
    target.flush()
