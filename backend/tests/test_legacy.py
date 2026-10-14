"""Offline historical-prefix conversion and reproducible sampling checks."""
import copy
from contextlib import redirect_stdout
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.judge import build_judge_messages
from research.legacy import legacy_public_game, main, read_export, sample_legacy_games
from research.openrouter import RequestBudgetExhausted


def row(order, actor, message):
    return {"id": f"t{order}", "order": order, "agent_id": actor, "message": message, "created_at": "2025-01-01"}


def legacy_record(match_id="match-1"):
    return {
        "record_type": "legacy_match", "schema_version": 1,
        "match": {"id": match_id, "agent1_action": "withhold", "agent2_action": "submit_evidence",
                  "agent1_default": False, "agent2_default": False, "created_at": "2025-01-01"},
        "agents": {"agent1": {"id": "original-a", "name": "historical/a"},
                   "agent2": {"id": "original-b", "name": "historical/b"}},
        "transcripts": [row(0, 0, "Original game setting"), row(1, 2, "_"),
                        row(2, 1, "I will withhold."), row(3, 2, "I will withhold too."),
                        row(4, 2, "action completed"), row(5, 0, "Now submit your decision."),
                        row(6, 1, "SECRET_PRIVATE_DECISION")],
        "provenance": {"historical_api_game": True, "missing": ["activations"]},
    }


class LegacyPrefixTests(unittest.TestCase):
    def test_action_acknowledgement_ends_safe_prefix_before_private_followup(self):
        record = legacy_record()
        record["transcripts"].reverse()
        game = legacy_public_game(record)
        self.assertEqual(game["setting"], "Original game setting")
        self.assertEqual(game["models"], ["historical/a", "historical/b"])
        self.assertEqual(game["source_match_id"], "match-1")
        self.assertEqual([m["content"] for m in game["public_messages"]], ["I will withhold.", "I will withhold too."])
        self.assertEqual(game["public_prefix_cutoff"]["reason"], "action_acknowledgement")
        self.assertEqual(game["public_source_map"][0], {"turn": 2, "transcript_id": "t2", "source_order": 2})
        encoded = json.dumps(build_judge_messages(game))
        self.assertNotIn("SECRET_PRIVATE_DECISION", encoded)
        self.assertNotIn("action completed", encoded)
        self.assertNotIn("stored_actions", encoded)

    def test_first_later_system_instruction_ends_prefix_without_acknowledgement(self):
        record = legacy_record()
        record["transcripts"] = [row(0, 0, "Rules"), row(1, 1, "I will withhold."),
                                 row(2, 0, "The other agent has submitted their decision. You must now submit your decision."),
                                 row(3, 2, "SECRET_AFTER_FORCED_INSTRUCTION")]
        game = legacy_public_game(record)
        self.assertEqual(len(game["public_messages"]), 1)
        self.assertEqual(game["public_prefix_cutoff"]["reason"], "later_system_message")
        self.assertNotIn("SECRET_AFTER_FORCED_INSTRUCTION", json.dumps(build_judge_messages(game)))

    def test_any_later_system_message_is_a_conservative_boundary(self):
        record = legacy_record()
        record["transcripts"].insert(3, row(2, 0, "Unrecognized private control message"))
        game = legacy_public_game(record)
        self.assertEqual(game["public_prefix_cutoff"]["reason"], "later_system_message")
        self.assertNotIn("I will withhold too.", json.dumps(game["public_messages"]))

    def test_defaulted_stored_withhold_is_never_an_observed_cooperative_action(self):
        record = legacy_record()
        record["match"]["agent1_default"] = True
        game = legacy_public_game(record)
        self.assertIsNone(game["actions"][1])
        self.assertEqual(game["actions"][2], "submit_evidence")
        self.assertEqual(game["stored_actions"]["1"], "withhold")
        self.assertTrue(game["default_flags"]["1"])
        self.assertEqual(game["status"], "invalid")
        self.assertEqual(sample_legacy_games([record])["games"], [])
        self.assertIsNone(sample_legacy_games([record], include_invalid=True)["games"][0]["actions"][1])

    def test_missing_default_flag_or_invalid_action_excluded_by_default(self):
        for changes in ({"agent1_default": None}, {"agent1_default": "false"}, {"agent1_default": 0}, {"agent1_action": "idle"}):
            record = legacy_record()
            record["match"].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(legacy_public_game(record)["actions"][1])
                self.assertEqual(sample_legacy_games([record])["eligible_games"], 0)

    def test_requires_original_initial_system_setting(self):
        record = legacy_record()
        record["transcripts"].pop(0)
        with self.assertRaises(ValueError):
            legacy_public_game(record)

    def test_source_ids_cannot_escape_the_artifact_directory(self):
        for match_id in ("../outside", "unsafe/name", "unsafe\\name"):
            with self.subTest(match_id=match_id), self.assertRaises(ValueError):
                legacy_public_game(legacy_record(match_id))

    def test_only_participants_and_nonblank_nonseed_messages_included(self):
        record = legacy_record()
        record["transcripts"] = [row(0, 0, "Rules"), row(1, 2, "_"), row(2, 1, "  "),
                                 row(3, 99, "UNKNOWN_ACTOR"), row(4, 1, "A public sentence.")]
        self.assertEqual([m["content"] for m in legacy_public_game(record)["public_messages"]], ["A public sentence."])


class LegacySamplingTests(unittest.TestCase):
    def test_sample_is_seeded_not_selected_on_promise_or_action_content(self):
        records = [legacy_record(f"match-{i:03d}") for i in range(30)]
        first = sample_legacy_games(records, limit=7, seed=81)
        reversed_source = sample_legacy_games(list(reversed(records)), limit=7, seed=81)
        self.assertEqual([g["source_match_id"] for g in first["games"]], [g["source_match_id"] for g in reversed_source["games"]])
        altered = copy.deepcopy(records)
        for record in altered:
            record["match"]["agent1_action"] = "submit_evidence"
            record["transcripts"][2]["message"] = "No promises here."
        other = sample_legacy_games(altered, limit=7, seed=81)
        self.assertEqual([g["source_match_id"] for g in first["games"]], [g["source_match_id"] for g in other["games"]])
        self.assertEqual(first["eligible_games"], 30)
        self.assertEqual(len(first["games"]), 7)

    def test_duplicate_match_ids_are_not_counted_as_independent_samples(self):
        with self.assertRaises(ValueError):
            sample_legacy_games([legacy_record(), legacy_record()])

    def test_prepare_only_persists_selection_without_provider_or_database_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jsonl.gz"
            with gzip.open(source, "wt") as stream:
                for i in range(4):
                    stream.write(json.dumps(legacy_record(f"match-{i}")) + "\n")
            self.assertEqual(len(list(read_export(source))), 4)
            run_dir = root / "labels"
            args = ["--source", str(source), "--run-dir", str(run_dir), "--limit", "2", "--prepare-only"]
            with patch("research.legacy.fetch_metadata") as fetch, patch("research.legacy.FreeClient") as client, patch("research.legacy.ResearchStore") as store, redirect_stdout(io.StringIO()):
                main(args)
                main(args)
                fetch.assert_not_called()
                client.assert_not_called()
                store.assert_not_called()
            manifest = json.loads((run_dir / "manifest.json").read_text())
            summary = json.loads((run_dir / "summary.json").read_text())
            self.assertEqual(len(manifest["selection"]), 2)
            self.assertEqual(len(list((run_dir / "games").glob("*.json"))), 2)
            self.assertEqual(summary["unjudged_games"], 2)
            self.assertEqual(summary["judged_games"], 0)
            self.assertEqual(summary["judge_error_games"], 0)
            self.assertEqual(manifest["status"], "prepared")

    def test_cli_uses_free_judge_public_input_and_new_research_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jsonl"
            source.write_text(json.dumps(legacy_record()) + "\n")
            route = {"id": "cohere/north-mini-code:free", "architecture": {"output_modalities": ["text"]},
                     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": []}
            claims = [{"actor_id": str(actor), "promise_type": "none", "promised_action": None,
                       "evidence": None, "condition": None, "retracted": False, "retraction_evidence": None,
                       "changed_information": False, "changed_information_evidence": None} for actor in (1, 2)]
            with patch("research.legacy.fetch_metadata", return_value=([route], {})), patch("research.legacy.FreeClient") as client_type, patch("research.legacy.ResearchStore") as store_type, patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}), redirect_stdout(io.StringIO()):
                client = client_type.return_value
                client.calls, client.cost = 1, 0.0
                client.complete.return_value = {"choices": [{"message": {"content": json.dumps({"claims": claims})}}]}
                run_dir = root / "labels"
                main(["--source", str(source), "--run-dir", str(run_dir), "--limit", "1",
                      "--ignore-provider", "google-ai-studio", "--ignore-provider", "google-vertex"])
                self.assertEqual(client_type.call_args.kwargs["ignored_providers"], ["google-ai-studio", "google-vertex"])
                self.assertEqual(client.complete.call_args.args[0], route["id"])
                sent = json.dumps(client.complete.call_args.args[1])
                self.assertNotIn("SECRET_PRIVATE_DECISION", sent)
                self.assertNotIn("stored_actions", sent)
                store = store_type.return_value
                self.assertEqual(store.put_game.call_count, 1)
                self.assertEqual(store.put_judgment.call_count, 1)
                self.assertGreaterEqual(store.put_run.call_count, 2)
                store.close.assert_called_once()
            manifest = json.loads((run_dir / "manifest.json").read_text())
            judgment = json.loads(next((run_dir / "judgments").glob("*.json")).read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["reported_cost_usd"], 0)
            self.assertEqual(judgment["source_match_id"], "match-1")
            self.assertEqual(judgment["models"], ["historical/a", "historical/b"])

    def test_budget_exhaustion_leaves_sample_unjudged_for_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jsonl"
            source.write_text(json.dumps(legacy_record()) + "\n")
            route = {"id": "cohere/north-mini-code:free", "architecture": {"output_modalities": ["text"]},
                     "pricing": {"prompt": "0", "completion": "0"}}
            with patch("research.legacy.fetch_metadata", return_value=([route], {})), patch("research.legacy.FreeClient") as client_type, patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}), redirect_stdout(io.StringIO()):
                client = client_type.return_value
                client.calls, client.cost = 0, 0.0
                client.complete.side_effect = RequestBudgetExhausted("Daily free quota exhausted")
                run_dir = root / "labels"
                main(["--source", str(source), "--run-dir", str(run_dir), "--limit", "1", "--no-db"])
            manifest = json.loads((run_dir / "manifest.json").read_text())
            summary = json.loads((run_dir / "summary.json").read_text())
            self.assertEqual(manifest["status"], "partial")
            self.assertEqual(summary["unjudged_games"], 1)
            self.assertEqual(summary["judge_error_games"], 0)
            self.assertEqual(list((run_dir / "judgments").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
