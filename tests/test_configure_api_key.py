import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


TARGET = Path(__file__).resolve().parents[1] / "scripts" / "configure_api_key.py"
SPEC = importlib.util.spec_from_file_location("right_code_configure_api_key", TARGET)
CONFIG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CONFIG)


class RightCodeConfigurationTests(unittest.TestCase):
    def test_save_and_check_api_key_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "right-code" / "api_key"
            saved = CONFIG.save_api_key("  secret-test-key  ", key_path)

            self.assertEqual(saved, key_path)
            self.assertEqual(key_path.read_text(encoding="utf-8"), "secret-test-key")
            result = CONFIG.check_configuration(key_path)
            self.assertEqual(result["status"], "ready")
            self.assertNotIn("secret-test-key", str(result))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)

    def test_empty_api_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "api_key"
            with self.assertRaisesRegex(CONFIG.ConfigurationError, "cannot be empty"):
                CONFIG.save_api_key("   ", key_path)

    def test_missing_configuration_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "missing"
            with self.assertRaisesRegex(CONFIG.ConfigurationError, "No API key"):
                CONFIG.check_configuration(key_path)

    def test_windows_uses_local_hidden_dialog(self):
        with mock.patch.object(CONFIG.sys, "platform", "win32"):
            with mock.patch.object(
                CONFIG, "_prompt_with_windows_dialog", return_value="secret-test-key"
            ) as prompt:
                self.assertEqual(CONFIG.prompt_for_api_key(), "secret-test-key")
                prompt.assert_called_once_with()

    def test_windows_dialog_keeps_key_out_of_command_arguments(self):
        completed = mock.Mock(returncode=0, stdout="secret-test-key")
        with mock.patch.object(CONFIG.subprocess, "run", return_value=completed) as run:
            self.assertEqual(CONFIG._prompt_with_windows_dialog(), "secret-test-key")
            command = run.call_args.args[0]
            self.assertEqual(command[0], "powershell.exe")
            self.assertIn("-STA", command)
            self.assertNotIn("secret-test-key", command)


if __name__ == "__main__":
    unittest.main()
