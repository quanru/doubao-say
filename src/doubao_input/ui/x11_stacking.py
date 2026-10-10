"""Own the optional X11 stacking request and its bounded helper lifetime."""
import logging
from gi.repository import Gio, GLib
from doubao_input.doubao.host_tools import command_candidates

logger = logging.getLogger(__name__)


class X11Stacking:
    def __init__(self):
        self._process = None
        self._timeout = None

    def request(self, window) -> None:
        """Request stacking for this mapping without delaying GTK or activation."""
        self.cancel()
        commands = iter(command_candidates("wmctrl"))
        from gi.repository import GdkX11
        xid = GdkX11.X11Surface.get_xid(window.get_surface())
        display = window.get_display()
        # The helper uses a separate connection; submit GTK's map request first.
        display.flush()
        display_name = display.get_name()
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        launcher.setenv("DISPLAY", display_name, True)

        def start_next():
            if not window.get_mapped():
                return
            for prefix in commands:
                if prefix[0] == "flatpak-spawn":
                    # Killing the wrapper must also stop its host-side command.
                    prefix = [*prefix[:1], "--watch-bus", f"--env=DISPLAY={display_name}", *prefix[1:]]
                try:
                    process = launcher.spawnv([*prefix, "-i", "-r", hex(xid), "-b", "add,above"])
                except GLib.Error:
                    continue
                self._process = process
                self._timeout = GLib.timeout_add(500, expired)
                process.wait_check_async(None, completed)
                return
            logger.warning("X11 overlay stacking unavailable; install wmctrl or check the window manager")

        def completed(process, result):
            try:
                success = process.wait_check_finish(result)
            except GLib.Error:
                success = False
            # A hidden/remapped overlay may already have a different request.
            if self._process is not process:
                return
            self._process = None
            if self._timeout is not None:
                GLib.source_remove(self._timeout)
                self._timeout = None
            if not success:
                start_next()

        def expired():
            self._timeout = None
            self.cancel()
            logger.warning("X11 overlay stacking request timed out")
            return GLib.SOURCE_REMOVE

        start_next()

    def cancel(self, *_args) -> None:
        if self._timeout is not None:
            GLib.source_remove(self._timeout)
            self._timeout = None
        process, self._process = self._process, None
        if process is not None:
            process.force_exit()
