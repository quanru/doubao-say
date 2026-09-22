from types import SimpleNamespace
from unittest import TestCase

from doubao_input.voxtype.runtime import daemon_state, inspect_runtime


class VoxtypeRuntimeTest(TestCase):
    def test_detects_stable_record_contract_and_optional_osd_flag(self):
        def run(command):
            if command[-1] == "--version":
                return SimpleNamespace(returncode=0, stdout="voxtype 1.0.1\n")
            if command[2] == "start":
                return SimpleNamespace(
                    returncode=0, stdout="--file PATH\n--no-osd\n")
            return SimpleNamespace(
                returncode=0, stdout="--wait\n--timeout SECONDS\n")

        runtime = inspect_runtime(which=lambda _name: "/usr/bin/voxtype", runner=run)
        self.assertEqual(runtime.version, "1.0.1")
        self.assertTrue(runtime.supports_no_osd)

    def test_rejects_old_or_incomplete_cli(self):
        def old(command):
            return SimpleNamespace(returncode=0, stdout="voxtype 0.7.5\n")

        with self.assertRaisesRegex(RuntimeError, "1.0.0"):
            inspect_runtime(which=lambda _name: "/voxtype", runner=old)

    def test_reads_daemon_json_state(self):
        runtime = SimpleNamespace(executable="/voxtype")
        runner = lambda _command: SimpleNamespace(
            returncode=0, stdout='{"text":"V","alt":"idle","class":"idle"}')
        self.assertEqual(daemon_state(runtime, runner=runner), "idle")

    def test_rejects_missing_daemon(self):
        runtime = SimpleNamespace(executable="/voxtype")
        runner = lambda _command: SimpleNamespace(returncode=1, stdout="")
        with self.assertRaisesRegex(RuntimeError, "not running"):
            daemon_state(runtime, runner=runner)
