import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LoadSettingsTests(unittest.TestCase):
    def test_reads_bot_token_from_environment_mapping(self):
        from app.config import load_settings

        settings = load_settings({"BOT_TOKEN": "test-token", "APP_ENV": "test"})

        self.assertEqual(settings.bot_token, "test-token")
        self.assertEqual(settings.app_env, "test")

    def test_requires_bot_token(self):
        from app.config import load_settings

        with self.assertRaisesRegex(RuntimeError, "BOT_TOKEN"):
            load_settings({"BOT_TOKEN": "   "})

    def test_reads_windows_bom_encoded_dotenv_file(self):
        from app.config import load_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "BOT_TOKEN=test-token\nAPP_ENV=local\n",
                encoding="utf-8-sig",
            )

            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(dotenv_path=dotenv_path)

        self.assertEqual(settings.bot_token, "test-token")
        self.assertEqual(settings.app_env, "local")


if __name__ == "__main__":
    unittest.main()
