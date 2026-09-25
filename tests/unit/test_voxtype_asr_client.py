import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.voxtype.asr_client import VoxtypeASRClient
from doubao_input.voxtype.runtime import VoxtypeRuntime


class FakeCommands:
    def __init__(self, transcript="local transcript", stop_code=0):
        self.transcript = transcript
        self.stop_code = stop_code
        self.commands = []
        self.path = None

    def __call__(self, command, *, timeout):
        self.commands.append(command)
        if command[1:3] == ["record", "start"]:
            file_arg = next(value for value in command if value.startswith("--file="))
            self.path = Path(file_arg.removeprefix("--file="))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:3] == ["record", "stop"]:
            if self.stop_code == 0:
                self.path.write_text(self.transcript)
                Path(f"{self.path}.done").write_text("ok")
            return SimpleNamespace(
                returncode=self.stop_code, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class VoxtypeASRClientTest(TestCase):
    runtime = VoxtypeRuntime("/usr/bin/voxtype", "1.0.1", True)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime_patch = patch(
            "doubao_input.voxtype.asr_client._private_runtime_dir",
            return_value=Path(self.directory.name),
        )
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

    def client(self, commands, state="idle"):
        client = VoxtypeASRClient(
            commands,
            lambda _runtime, **_kwargs: state,
        )
        self.addCleanup(client.disconnect)
        return client

    def test_records_to_private_file_and_delivers_final_text(self):
        commands = FakeCommands()
        client = self.client(commands)
        opened, finished = threading.Event(), threading.Event()
        results = []
        client.on_open = opened.set
        client.on_result = results.append
        client.on_finish = finished.set
        client.connect(self.runtime)
        self.assertTrue(opened.wait(2))
        client.finish_sending()
        self.assertTrue(finished.wait(2))
        self.assertEqual(results, ["local transcript"])
        start = commands.commands[0]
        self.assertIn("--no-osd", start)
        self.assertIn("--wait", commands.commands[1])
        self.assertFalse(commands.path.exists())
        self.assertFalse(Path(f"{commands.path}.done").exists())
        self.assertFalse(any(command[-1] == "cancel" for command in commands.commands))

    def test_empty_completion_finishes_without_result(self):
        commands = FakeCommands(stop_code=3)
        client = self.client(commands)
        opened, finished, result = threading.Event(), threading.Event(), Mock()
        client.on_open = opened.set
        client.on_finish = finished.set
        client.on_result = result
        client.connect(self.runtime)
        self.assertTrue(opened.wait(2))
        client.finish_sending()
        self.assertTrue(finished.wait(2))
        result.assert_not_called()

    def test_does_not_take_over_an_existing_voxtype_session(self):
        commands = FakeCommands()
        client = self.client(commands, state="recording")
        failed = threading.Event()
        client.on_error = lambda _error: failed.set()
        client.connect(self.runtime)
        self.assertTrue(failed.wait(2))
        client.disconnect()
        self.assertFalse(any(command[-1] == "cancel" for command in commands.commands))

    def test_cancel_only_stops_a_recording_started_by_this_client(self):
        commands = FakeCommands()
        client = self.client(commands)
        opened = threading.Event()
        client.on_open = opened.set
        client.connect(self.runtime)
        self.assertTrue(opened.wait(2))
        client.disconnect()
        self.assertTrue(any(command[-1] == "cancel" for command in commands.commands))

    def test_stop_waits_for_slow_start_instead_of_losing_completion(self):
        commands = FakeCommands()
        start_gate = threading.Event()
        client = VoxtypeASRClient(
            commands,
            lambda _runtime, **_kwargs: start_gate.wait(10) and "idle",
        )
        self.addCleanup(client.disconnect)
        finished = threading.Event()
        client.on_finish = finished.set
        client.connect(self.runtime)
        client.finish_sending()

        try:
            time.sleep(5.1)
            start_gate.set()
            self.assertTrue(finished.wait(2))
            self.assertTrue(any(
                command[1:3] == ["record", "stop"] for command in commands.commands
            ))
        finally:
            start_gate.set()
