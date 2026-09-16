"""Entry point: `python -m doubao_input`."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from doubao_input.desktop import is_x11


def _preload_layer_shell() -> None:
    """Re-exec once with gtk4-layer-shell preloaded before GTK/Wayland."""
    if (is_x11() or os.environ.get("GDK_BACKEND") == "x11"
            or os.environ.get("DOUBAO_LAYER_SHELL_PRELOADED") == "1"):
        return
    try:
        import ctypes.util

        library = ctypes.util.find_library("gtk4-layer-shell")
        if not library:
            return
        env = os.environ.copy()
        current = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = f"{library}:{current}" if current else library
        env["DOUBAO_LAYER_SHELL_PRELOADED"] = "1"
        os.execvpe(
            sys.executable,
            [sys.executable, "-m", "doubao_input", *sys.argv[1:]],
            env,
        )
    except (OSError, AttributeError):
        # Non-Omarchy systems may not ship layer-shell. Overlay has a safe
        # compositor-positioned fallback in that case.
        pass


def main() -> int:
    if "--check" in sys.argv[1:]:
        from doubao_input.preflight import main as check
        return check()
    from doubao_input.plugin_launch import installed_root, is_plugin, launch
    if is_plugin(installed_root()) and not any(
            flag in sys.argv[1:] for flag in ("--background", "--trigger-debug")):
        try:
            launch(show="--wait-for-service" not in sys.argv[1:])
            return 0
        except Exception as error:
            print(f"Could not open Doubao Say: {error}", file=sys.stderr)
            return 1
    _preload_layer_shell()
    # Importing app imports GTK, so it must happen after the preload above.
    from doubao_input.app import DoubaoInputApp

    trigger_debug = "--trigger-debug" in sys.argv[1:]
    background = "--background" in sys.argv[1:] or trigger_debug
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        log_dir = state_home / "doubao-say"
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_path = log_dir / "app.log"
        file_handler = RotatingFileHandler(log_path, maxBytes=256_000,
                                           backupCount=1, encoding="utf-8")
        os.chmod(log_path, 0o600)
        handlers.append(file_handler)
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)
    app = DoubaoInputApp(background=background, trigger_debug=trigger_debug)
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
