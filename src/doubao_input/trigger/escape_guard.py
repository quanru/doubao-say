"""Lease a compositor-owned Escape binding only during cancellable input.

Evdev still delivers cancellation to the app; Hyprland prevents the same press
from reaching the foreground. The compositor lease expires after an app crash.
"""
import json
import os
import subprocess
import time


class EscapeGuard:
    def __init__(self, error=lambda message: None):
        self.enabled = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and (
            os.environ.get("DOUBAO_SAY_TRIGGER_BACKEND", "evdev") != "portal")
        self.active = self.held = False
        self._renewed = 0
        self._name = f"doubao_escape_{os.getpid()}"
        self._error = error

    def _eval(self, code):
        result = subprocess.run(["hyprctl", "eval", code], capture_output=True,
                                text=True, timeout=0.5, check=True)
        if result.stdout.strip() != "ok":
            raise RuntimeError("Hyprland rejected the temporary Escape binding")

    def edge(self, pressed):
        self.held = pressed and self.active

    def sync(self, busy):
        if not self.enabled:
            return
        wanted = busy or self.held
        try:
            if wanted and (not self.active or time.monotonic() - self._renewed >= 0.5):
                if not self.active:
                    binds = json.loads(subprocess.check_output(["hyprctl", "binds", "-j"], timeout=0.5))
                    if any(b.get("modmask") == 0 and (b.get("key", "").lower() == "escape"
                           or b.get("keycode") == 9) for b in binds):
                        raise RuntimeError("Escape already has a global binding; it was left unchanged")
                name = self._name
                self._eval(f'''
                    if not {name} then
                        {name} = {{ generation = 0 }}
                        {name}.bind = hl.bind("Escape", function() end,
                            {{ description = "Doubao Say: cancel input" }})
                    end
                    local lease = {name}
                    lease.generation = lease.generation + 1
                    local generation = lease.generation
                    hl.timer(function()
                        if {name} == lease and lease.generation == generation then
                            lease.bind:unbind()
                            {name} = nil
                        end
                    end, {{ timeout = 2000, type = "oneshot" }})
                ''')
                self.active = True
                self._renewed = time.monotonic()
            elif not wanted and self.active:
                self.close()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            self.enabled = False
            self._error(str(error))

    def close(self):
        if self.active:
            try:
                self._eval(f"if {self._name} then {self._name}.bind:unbind(); {self._name} = nil end")
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass  # The compositor's two-second lease is the fallback.
        self.active = self.held = False
