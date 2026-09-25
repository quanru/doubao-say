import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from doubao_input.voxtype.control import inspect_details, launch_configure, select_model
from doubao_input.voxtype.runtime import VoxtypeRuntime


class VoxtypeControlTest(TestCase):
    runtime = VoxtypeRuntime("/usr/bin/voxtype", "1.0.1", True)

    def test_reads_extended_status_and_schema_contracts(self):
        def run(command):
            if "status" in command:
                payload = {
                    "alt": "idle",
                    "model": "large-v3-turbo",
                    "device": "Desk microphone",
                    "backend": "Vulkan",
                }
            elif "models" in command:
                payload = {"engines": {"whisper": {"models": [
                    {"name": "base", "download_arg": "base",
                     "installed": True},
                    {"name": "large-v3-turbo",
                     "download_arg": "large-v3-turbo", "installed": True},
                    {"name": "small", "download_arg": "small",
                     "installed": False},
                ]}}}
            else:
                payload = {
                    "schema_version": 1,
                    "voxtype_version": "1.0.1",
                    "daemon_version_label": "1.0.1",
                    "config_path": "/home/test/.config/voxtype/config.toml",
                    "engine": "whisper",
                    "keys": [],
                }
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr="")

        details = inspect_details(runtime=self.runtime, runner=run)
        self.assertEqual(details.state, "idle")
        self.assertEqual(details.engine, "whisper")
        self.assertEqual(details.model, "large-v3-turbo")
        self.assertEqual(details.backend, "Vulkan")
        self.assertEqual(details.schema_version, 1)
        self.assertEqual(details.installed_models, ("base", "large-v3-turbo"))

    def test_rejects_stopped_daemon(self):
        runner = lambda _command: SimpleNamespace(
            returncode=0,
            stdout='{"alt":"stopped"}',
            stderr="",
        )
        with self.assertRaisesRegex(RuntimeError, "not running"):
            inspect_details(runtime=self.runtime, runner=runner)

    def test_selected_model_updates_config_and_restarts_daemon(self):
        state = {"model": "sensevoice-small", "pending": None}
        commands = []

        def run(command):
            commands.append(command)
            if "status" in command:
                payload = {"alt": "idle", "model": state["model"]}
            elif "schema" in command:
                payload = {"engine": "sensevoice"}
            elif "models" in command:
                payload = {"engines": {"sensevoice": {"models": [
                    {"download_arg": "sensevoice-small", "installed": True},
                    {"download_arg": "sensevoice-small-fp32", "installed": True},
                ]}}}
            else:
                state["pending"] = command[-1]
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        def restart():
            state["model"] = state["pending"]
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        select_model("sensevoice-small-fp32", runtime=self.runtime,
                     runner=run, restart=restart)
        self.assertEqual(state["model"], "sensevoice-small-fp32")
        self.assertIn([self.runtime.executable, "config", "set",
                       "sensevoice.model", "sensevoice-small-fp32"], commands)

    def test_opens_voxtype_configure_in_available_terminal(self):
        popen = Mock()
        paths = {"kitty": "/usr/bin/kitty"}
        launch_configure(
            runtime=self.runtime,
            which=paths.get,
            popen=popen,
            environment={},
        )
        command = popen.call_args.args[0]
        self.assertEqual(command, [
            "/usr/bin/kitty", "-e", "/usr/bin/voxtype", "configure",
        ])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_reports_when_no_terminal_is_available(self):
        with self.assertRaisesRegex(RuntimeError, "No supported terminal"):
            launch_configure(
                runtime=self.runtime,
                which=lambda _name: None,
                popen=Mock(),
                environment={},
            )
