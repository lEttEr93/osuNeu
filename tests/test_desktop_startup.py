"""Exercise renderer recovery without depending on Qt or a display."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from osuneu.desktop import launch


class StartupTests(unittest.TestCase):
    def exercise(self, normal_exit, compatibility_ready):
        scratch = Path(os.environ.get("AI_ROOT", "D:/AI")) / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            calls = []

            def spawn(command, **kwargs):
                compat = kwargs["env"].get("QTWEBENGINE_DISABLE_SANDBOX") == "1"
                calls.append((command, kwargs["env"]))
                if compat and compatibility_ready:
                    Path(command[command.index("--ready-file") + 1]).write_text("ready")
                return SimpleNamespace(poll=lambda: -1 if compat else normal_exit,
                                       wait=lambda: 0)

            env = {"AI_ROOT": str(root), "AI_CACHES": str(root / "cache")}
            with patch.dict(os.environ, env), patch("osuneu.desktop.subprocess.Popen", spawn):
                os.environ.pop("QTWEBENGINE_DISABLE_SANDBOX", None)
                code = launch(SimpleNamespace(port=8766, data_dir=None, debug_port=None))
            config = root / "cache" / "osuneu" / "renderer.json"
            return code, calls, json.loads(config.read_text()) if config.exists() else None

    def test_native_crash_retries_and_remembers_working_renderer(self):
        code, calls, config = self.exercise(-1073741819, True)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("QTWEBENGINE_DISABLE_SANDBOX", calls[0][1])
        self.assertEqual(calls[1][1]["QTWEBENGINE_DISABLE_SANDBOX"], "1")
        self.assertEqual(config, {"compatibility": True})

    def test_user_close_does_not_reopen_window(self):
        code, calls, config = self.exercise(0, False)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(config)

    def test_both_failures_stop_without_remembering_broken_renderer(self):
        code, calls, config = self.exercise(1, False)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(config)
