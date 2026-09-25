"""Guard the Debian install path against fetching executable Python packages."""
from pathlib import Path
import unittest
from unittest.mock import patch

from doubao_input import preflight


ROOT = Path(__file__).resolve().parents[2]


class DebianPackageTest(unittest.TestCase):
    def test_pipewire_runtime_does_not_require_portaudio(self):
        with patch.object(preflight, "check_system", return_value={"pw-record": True}), \
             patch.object(preflight, "_check_modules", return_value={"evdev": True, "websockets": True}) as modules:
            self.assertTrue(all(preflight.check_runtime().values()))
        modules.assert_called_once_with(("evdev", "websockets"))

    def test_runtime_dependencies_are_distribution_packages(self):
        control = (ROOT / "debian/control").read_text()
        postinst = (ROOT / "debian/postinst").read_text()
        rules = (ROOT / "debian/rules").read_text()

        for package in ("python3-websockets", "python3-evdev", "pipewire-bin"):
            self.assertIn(package, control)
        self.assertNotIn("pip", postinst)
        self.assertNotIn("venv", postinst)
        self.assertIn("exec /usr/bin/python3 -m doubao_input", rules)
