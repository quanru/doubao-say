import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / "tests/e2e/is-transient-midscene-failure.sh"


class MidsceneRetryClassifierTest(unittest.TestCase):
    def classify(self, content: str) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as log:
            log.write(content)
            log.flush()
            return subprocess.run(
                [CLASSIFIER, log.name],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_retries_network_and_model_protocol_failures(self):
        for message in (
            "AggregateError [ETIMEDOUT]",
            "XML parse error: Invalid parameters for action KeyboardPress",
            "Failed to parse action-param-json",
        ):
            with self.subTest(message=message):
                self.assertEqual(self.classify(message).returncode, 0)

    def test_does_not_retry_product_assertion_failures(self):
        for message in (
            "Assertion failed: the expected endpoint result is not visible",
            "Invalid parameters for action KeyboardPress",
            "No valid action generated for disabled product control",
        ):
            with self.subTest(message=message):
                self.assertEqual(self.classify(message).returncode, 1)


if __name__ == "__main__":
    unittest.main()
