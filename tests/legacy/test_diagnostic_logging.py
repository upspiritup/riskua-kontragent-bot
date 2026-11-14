import json
import tempfile
import unittest
from pathlib import Path


def parse_logged_payload(line: str) -> dict:
    return json.loads(line.split(" INFO ", 1)[-1])


class DiagnosticLoggingTests(unittest.TestCase):
    def test_line_capped_log_file_overwrites_after_limit(self):
        from app.services.diagnostic_logging import configure_diagnostic_logging, log_diagnostic_event

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "riskua_diagnostic.log"
            configure_diagnostic_logging(log_path=log_path, max_lines=3)

            for index in range(4):
                log_diagnostic_event("test_event", route="test", index=index)

            lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertLessEqual(len(lines), 3)
        self.assertIn('"index": 3', lines[-1])
        self.assertNotIn('"index": 0', "\n".join(lines))

    def test_diagnostic_log_sanitizes_secret_query_values(self):
        from app.services.diagnostic_logging import configure_diagnostic_logging, log_diagnostic_event

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "riskua_diagnostic.log"
            configure_diagnostic_logging(log_path=log_path, max_lines=20)
            log_diagnostic_event(
                "http_request",
                route="contact_fetch",
                url="https://example.test/path?token=secret-token&api_key=very-secret&q=01554522",
            )
            payload = parse_logged_payload(log_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(payload["url"], "https://example.test/path?token=<redacted>&api_key=<redacted>&q=01554522")
        self.assertNotIn("secret-token", json.dumps(payload))
        self.assertNotIn("very-secret", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
