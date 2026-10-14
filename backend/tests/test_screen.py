"""Offline checks of screening coverage, public evidence, and counting units."""

from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.judge import build_judge_messages
from research.screen import canonical_game, request_accounting, schedule, summarize


class ScheduleTests(unittest.TestCase):
    def test_every_pair_plays_both_speaking_orders_for_even_and_odd_catalogs(self):
        for model_ids in (["a", "b"], ["a", "b", "c"], ["a", "b", "c", "d"]):
            with self.subTest(model_ids=model_ids):
                games = schedule(model_ids, seed=41, repetitions=2)
                unordered_pairs = Counter(tuple(sorted(game["models"])) for game in games)
                seats = defaultdict(list)
                for game in games:
                    pair = tuple(game["models"])
                    self.assertEqual(len(set(pair)), 2)
                    self.assertTrue(set(pair).issubset(model_ids))
                    seats[tuple(sorted(pair))].append(pair)
                self.assertEqual(unordered_pairs, Counter({pair: 2 for pair in combinations(sorted(model_ids), 2)}))
                for pair_orders in seats.values():
                    self.assertEqual(pair_orders[0], pair_orders[1][::-1])
                self.assertEqual(len({game["game_id"] for game in games}), len(games))
                self.assertEqual(len({game["seed"] for game in games}), len(games))

    def test_schedule_reproducible_independent_of_catalog_order(self):
        ids = ["a", "b", "c", "d", "e"]
        self.assertEqual(schedule(ids, seed=17), schedule(list(reversed(ids)), seed=17))
        self.assertEqual(schedule(ids, seed=17), schedule(ids, seed=17))
        self.assertNotEqual(schedule(ids, seed=17), schedule(ids, seed=18))

    def test_each_repetition_covers_each_pair_once(self):
        ids = ["a", "b", "c", "d", "e"]
        games = schedule(ids, seed=9, repetitions=3)
        pair_count = len(ids) * (len(ids) - 1) // 2
        expected = {frozenset(pair) for pair in combinations(ids, 2)}
        self.assertEqual(len(games), pair_count * 3)
        for start in range(0, len(games), pair_count):
            self.assertEqual({frozenset(g["models"]) for g in games[start:start + pair_count]}, expected)
        self.assertEqual([g["models"] for g in games[:pair_count]], [g["models"] for g in games[2 * pair_count:]])


class PublicEvidenceTests(unittest.TestCase):
    def test_only_explicitly_public_event_text_reaches_judge(self):
        result = {
            "agent1_action": "submit_evidence", "agent2_action": "withhold",
            "message_history": [{"content": "LEGACY_PRIVATE_TEXT"}],
            "decision_events": [
                {"event_index": 0, "actor_id": 1, "assistant_text": "I will withhold.", "public_visibility": True,
                 "raw_response": "SECRET_RAW", "tool_calls": "SECRET_TOOL"},
                {"event_index": 1, "actor_id": 2, "assistant_text": "SECRET_PRIVATE", "public_visibility": False},
                {"event_index": 2, "actor_id": 1, "assistant_text": "SECRET_MISSING_MARKER"},
                {"event_index": 3, "actor_id": 2, "assistant_text": "Agreed.", "public_visibility": True},
            ],
        }
        canonical = canonical_game(result)
        self.assertEqual(canonical["public_messages"], [
            {"turn": 0, "actor_id": 1, "content": "I will withhold."},
            {"turn": 3, "actor_id": 2, "content": "Agreed."},
        ])
        self.assertEqual(canonical["actions"], {1: "submit_evidence", 2: "withhold"})
        messages = build_judge_messages(canonical)
        encoded = json.dumps(messages)
        for secret in ("LEGACY_PRIVATE_TEXT", "SECRET_RAW", "SECRET_TOOL", "SECRET_PRIVATE", "SECRET_MISSING_MARKER"):
            self.assertNotIn(secret, encoded)
        self.assertNotIn("actions", json.loads(messages[1]["content"]))

    def test_truthy_nonboolean_visibility_does_not_disclose_events(self):
        for visibility in ("private", "true", 1, [True], {"public": True}):
            with self.subTest(visibility=visibility):
                result = {"decision_events": [{"event_index": 0, "actor_id": 1,
                          "assistant_text": "PRIVATE_DECISION", "public_visibility": visibility}]}
                self.assertEqual(canonical_game(result)["public_messages"], [])

    def test_no_public_events_gives_empty_transcript_and_no_action_defaults(self):
        canonical = canonical_game({})
        self.assertEqual(canonical["public_messages"], [])
        self.assertEqual(canonical["actions"], {1: None, 2: None})


class SummaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.run_dir = Path(temp.name)
        for folder in ("games", "judgments"):
            (self.run_dir / folder).mkdir()
        self.manifest = {
            "run_id": "test-run", "models": [{"id": name} for name in ("a", "b", "c")],
            "schedule": [{"game_id": f"g{i}"} for i in range(1, 5)], "excluded": [{"id": "not-free"}],
        }

    def save_game(self, game_id, models, status, claim_statuses=None, judge_error=False):
        game = {"game_id": game_id, "models": models, "status": status}
        (self.run_dir / "games" / f"{game_id}.json").write_text(json.dumps(game))
        if claim_statuses is not None:
            judgment = {"judge_status": "ok", "claims": [
                {"actor_id": str(actor), "status": claim_status}
                for actor, claim_status in enumerate(claim_statuses, 1)
            ]}
        elif judge_error:
            judgment = {"judge_status": "error", "claims": [], "error": {"type": "invalid_judgment"}}
        else:
            return
        (self.run_dir / "judgments" / f"{game_id}.json").write_text(json.dumps(judgment))

    def test_unique_games_and_participant_claim_observations_are_distinct(self):
        self.save_game("g1", ["a", "b"], "completed", ["fulfilled", "broken"])
        self.save_game("g2", ["b", "a"], "invalid", ["invalid", "no_promise"])
        self.save_game("g3", ["a", "b"], "provider_error")
        self.save_game("g4", ["a", "c"], "completed", judge_error=True)
        summary = summarize(self.run_dir, self.manifest)
        self.assertEqual(summary["completed_or_invalid_games"], 3)
        self.assertEqual(summary["scheduled_games"], 4)
        a, b, c = (summary["models"][name] for name in ("a", "b", "c"))
        self.assertEqual(a["games_attempted"], 4)
        self.assertEqual(a["games_completed"], 2)
        self.assertEqual(a["games_invalid"], 1)
        self.assertEqual(a["games_provider_error"], 1)
        self.assertEqual(a["fulfilled"], 1)
        self.assertEqual(a["no_promise"], 1)
        self.assertEqual(a["judge_errors"], 1)
        self.assertEqual(b["games_attempted"], 3)
        self.assertEqual(b["games_invalid"], 1)
        self.assertEqual(b["invalid"], 1)  # A claim error must not double-count the invalid game.
        self.assertEqual(b["broken"], 1)
        self.assertEqual(c["judge_errors"], 1)
        self.assertEqual(c.get("no_promise", 0), 0)
        self.assertEqual(len(summary["broken_promise_examples"]), 1)
        self.assertEqual(summary["broken_promise_examples"][0]["model"], "b")
        self.assertEqual(summary["broken_promise_examples"][0]["game_id"], "g1")
        saved = json.loads((self.run_dir / "summary.json").read_text())
        self.assertEqual(saved["models"], summary["models"])

    def test_resummarizing_does_not_accumulate_counts(self):
        self.save_game("g1", ["a", "b"], "completed", ["fulfilled", "broken"])
        first = summarize(self.run_dir, self.manifest)
        second = summarize(self.run_dir, self.manifest)
        self.assertEqual(first["models"], second["models"])
        self.assertEqual(second["completed_or_invalid_games"], 1)

    def test_unjudged_games_do_not_become_nonpromises(self):
        self.save_game("g1", ["a", "b"], "completed")
        summary = summarize(self.run_dir, self.manifest)
        for model in ("a", "b"):
            self.assertEqual(summary["models"][model]["games_completed"], 1)
            for label in ("no_promise", "fulfilled", "broken", "judge_errors"):
                self.assertEqual(summary["models"][model].get(label, 0), 0)

    def test_all_games_finished_is_not_complete_until_every_judgment_succeeds(self):
        for game_id in ("g1", "g2", "g3"):
            self.save_game(game_id, ["a", "b"], "completed", ["fulfilled", "broken"])
        self.save_game("g4", ["a", "b"], "invalid")
        summary = summarize(self.run_dir, self.manifest)
        self.assertTrue(summary["games_complete"])
        self.assertFalse(summary["analysis_complete"])
        self.assertEqual(summary["missing_judgments"], 1)
        self.save_game("g4", ["a", "b"], "invalid", judge_error=True)
        summary = summarize(self.run_dir, self.manifest)
        self.assertFalse(summary["analysis_complete"])
        self.assertEqual(summary["failed_judgments"], 1)
        self.assertEqual(summary["missing_judgments"], 0)
        self.save_game("g4", ["a", "b"], "invalid", ["invalid", "no_promise"])
        summary = summarize(self.run_dir, self.manifest)
        self.assertTrue(summary["analysis_complete"])
        self.assertEqual(summary["successfully_judged_games"], 4)

    def test_cumulative_reported_cost_survives_resume_and_duplicate_records(self):
        records = [
            {"event": "request_started", "request_id": "old", "invocation_id": "first"},
            {"event": "request_finished", "request_id": "old", "invocation_id": "first", "response": {"usage": {"cost": "0.03"}}},
            {"event": "request_finished", "request_id": "old", "invocation_id": "first", "response": {"usage": {"cost": "0.03"}}},
            {"event": "request_started", "request_id": "new", "invocation_id": "second"},
            {"event": "request_finished", "request_id": "new", "invocation_id": "second", "response": {"usage": {"cost": 0}}},
            {"event": "request_finished", "request_id": "error", "response": {"error": "unavailable"}},
        ]
        (self.run_dir / "requests.jsonl").write_text("\n".join(json.dumps(record) for record in records) + '\n{"unfinished":')
        accounting = request_accounting(self.run_dir)
        self.assertEqual(accounting["reported_cost_usd"], 0.03)
        self.assertEqual(accounting["request_finished"], 3)
        self.assertEqual(accounting["request_started"], 2)
        self.assertEqual(accounting["cost_unreported_responses"], 1)
        self.assertEqual(accounting["journal_parse_errors"], 1)
        self.assertEqual(summarize(self.run_dir, self.manifest)["request_accounting"], accounting)


if __name__ == "__main__":
    unittest.main()
