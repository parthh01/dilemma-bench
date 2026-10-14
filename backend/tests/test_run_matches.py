"""Legacy invalid-result handling without importing database engines or calling APIs."""
import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_runner():
    db = types.ModuleType("db.definition")
    for name in ("create_tables", "get_or_create_agent", "get_or_create_agents", "get_played_pairs", "store_match_result"):
        setattr(db, name, Mock())
    spec = importlib.util.spec_from_file_location("offline_legacy_runner", BACKEND / "run_matches.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"db.definition": db}), patch("signal.signal"), patch("logging.FileHandler", return_value=logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


class LegacyInvalidTests(unittest.TestCase):
    def test_invalid_outcomes_are_journaled_without_elo_and_excluded_after_restart(self):
        module = load_runner()
        first, second = {"id": "test/first", "name": "First"}, {"id": "test/second", "name": "Second"}
        invalid = {"status": "invalid", "winner": None, "agent1_action": "idle", "agent2_action": "withhold",
                   "agent1_defaulted": True, "agent2_defaulted": False, "decision_events": [{"assistant_text": "Evidence retained"}]}
        for method in ("run_single_match_sync", "run_single_match"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temp:
                journal = Path(temp) / "invalid.jsonl"
                runner = module.MatchRunner(max_workers=1, invalid_results_path=journal)
                try:
                    with patch.object(runner, "create_llm_from_model", return_value=Mock()), patch.object(module, "play_match", AsyncMock(return_value=invalid)):
                        if method.endswith("_sync"):
                            handled = runner.run_single_match_sync(first, second, "agent-a", "agent-b")
                        else:
                            handled = asyncio.run(runner.run_single_match(first, second, "agent-a", "agent-b"))
                    self.assertTrue(handled)
                    module.store_match_result.assert_not_called()
                    self.assertEqual(runner.active_matches, 0)
                    record = json.loads(journal.read_text())
                    self.assertEqual(record["status"], "invalid")
                    self.assertIsNone(record["winner"])
                    self.assertEqual(record["agent1_action"], "idle")
                    self.assertEqual(record["decision_events"], invalid["decision_events"])
                finally:
                    runner.executor.shutdown()
                restarted = module.MatchRunner(max_workers=1, invalid_results_path=journal)
                try:
                    module.get_or_create_agents.return_value = {"test/first": "agent-a", "test/second": "agent-b"}
                    module.get_played_pairs.return_value = set()
                    self.assertEqual(restarted.find_unplayed_pairs([first, second]), [])
                    self.assertEqual(restarted.find_unplayed_pairs([second, first]), [])
                finally:
                    restarted.executor.shutdown()


if __name__ == "__main__":
    unittest.main()
