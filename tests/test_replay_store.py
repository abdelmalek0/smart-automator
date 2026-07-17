"""Tests for persisted replay script storage."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_automator.server import replay_store


class TestReplayStore(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_dir = Path(tmp)
            with patch.object(replay_store, "REPLAY_DIR", replay_dir):
                steps = [{"index": 1, "action": "go_to_url", "args": {"url": "https://example.com"}}]
                script = "# replay script"
                path = replay_store.save_run_replay("run-1", steps, script)

                self.assertTrue(path.is_file())
                self.assertTrue((replay_dir / "run-1.py").is_file())

                loaded = replay_store.load_run_replay("run-1")
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded["replay_steps"], steps)
                self.assertEqual(loaded["replay_script"], script)

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(replay_store, "REPLAY_DIR", Path(tmp)):
                self.assertIsNone(replay_store.load_run_replay("missing"))

    def test_load_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_dir = Path(tmp)
            bad = replay_dir / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with patch.object(replay_store, "REPLAY_DIR", replay_dir):
                self.assertIsNone(replay_store.load_run_replay("bad"))


if __name__ == "__main__":
    unittest.main()
