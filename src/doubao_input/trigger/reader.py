"""Combined ordinary-keyboard and optional dedicated-device trigger reader."""
from doubao_input.trigger.au05 import Au05Listener
from doubao_input.trigger.evdev_ptt import EvdevPtt


class TriggerReader:
    def __init__(self, on_press, on_release, on_error=None, on_key=None,
                 key_codes=None, on_aux=None, on_aux_error=None,
                 vibekey_enabled=False):
        self._keyboard = EvdevPtt(on_press, on_release, on_error=on_error,
                                  on_key=on_key, key_codes=key_codes)
        self._vibekey = (Au05Listener(on_aux or (lambda action, pressed: None),
                                     on_error=on_aux_error)
                         if vibekey_enabled else None)

    def start(self):
        keyboard = self._keyboard.start()
        vibekey = self._vibekey.start() if self._vibekey else False
        return keyboard or vibekey

    def stop(self):
        if self._vibekey:
            self._vibekey.stop()
        self._keyboard.stop()

    def is_running(self):
        return self._keyboard.is_running() or bool(
            self._vibekey and self._vibekey.is_running())
