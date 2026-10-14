"""Offline tests of game evidence, visibility, termination, and original payoffs."""

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.graph import Agent, play_match


def decision(action, text="", call_id="decision", **kwargs):
    return AIMessage(
        content=text,
        tool_calls=[{"name": action, "args": {"query": "private argument"}, "id": call_id}],
        **kwargs,
    )


class ScriptedModel:
    """Implements only the bind_tools/invoke contract; no network or credentials."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.requests.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def run_game(first, second, **kwargs):
    with redirect_stdout(io.StringIO()):
        return asyncio.run(play_match(first, second, **kwargs))


class GameEvidenceTests(unittest.TestCase):
    def test_action_preserves_assistant_text_and_raw_tool_evidence(self):
        model = ScriptedModel(decision(
            "submit_evidence", "I promise to withhold.",
            response_metadata={"finish_reason": "tool_calls", "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            usage_metadata={"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
        ))
        with redirect_stdout(io.StringIO()):
            response = Agent(model).get_response([SystemMessage(content="game"), HumanMessage(content="hello")])
        self.assertEqual(response["msg"], "I promise to withhold.")
        self.assertEqual(response["action"], "submit_evidence")
        self.assertTrue(response["decision_requested"])
        assistant, tool = response["response_events"]
        self.assertEqual(assistant["tool_calls"][0]["name"], "submit_evidence")
        self.assertEqual(assistant["usage_metadata"]["total_tokens"], 19)
        self.assertEqual(assistant["response_metadata"]["finish_reason"], "tool_calls")
        self.assertEqual(tool["type"], "tool")
        self.assertEqual(tool["tool_call_id"], "decision")
        json.dumps(response)

    def test_decision_turn_speech_is_public_but_tool_details_and_reasoning_are_private(self):
        first = ScriptedModel(
            AIMessage(content="I will withhold."),
            decision("submit_evidence", [
                {"type": "thinking", "thinking": "Private reasoning block"},
                {"type": "text", "text": "I still promise to withhold."},
            ], call_id="first", additional_kwargs={"reasoning_content": "Private reasoning metadata"}),
        )
        second = ScriptedModel(AIMessage(content="Agreed."), decision("withhold", "Private forced-decision text", call_id="second"))
        journal = []
        result = run_game(first, second, event_callback=journal.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], 1)
        self.assertEqual(result["termination_reason"], "agent_decision")
        self.assertEqual(result["termination_actor_id"], 1)
        self.assertEqual(result["total_turns"], 3)
        self.assertEqual(result["total_model_calls"], 4)
        public = json.dumps(result["message_history"])
        self.assertIn("I will withhold.", public)
        self.assertIn("I still promise to withhold.", public)
        self.assertNotIn("private argument", public)
        self.assertNotIn("Private reasoning", public)
        self.assertNotIn("Private forced-decision text", public)
        opponent_request = " ".join(str(message.content) for message in second.requests[-1])
        self.assertIn("I still promise to withhold.", opponent_request)
        self.assertNotIn("private argument", opponent_request)
        self.assertNotIn("Private reasoning", opponent_request)
        self.assertNotIn("tool_calls", json.dumps(result["message_history"]))
        self.assertEqual(second.requests[-1][-2].content, "I still promise to withhold.")
        self.assertIn("The other agent has ended the dialogue", opponent_request)
        self.assertEqual([event["public_visibility"] for event in journal], [True, True, True, False])
        self.assertEqual([event["actor_id"] for event in journal], [1, 2, 1, 2])
        self.assertEqual(journal[2]["assistant_text"], "I still promise to withhold.")
        self.assertIn("Private reasoning block", json.dumps(journal[2]["response_events"]))
        self.assertIn("Private reasoning metadata", json.dumps(journal[2]["response_events"]))
        self.assertEqual(journal[3]["assistant_text"], "Private forced-decision text")
        self.assertEqual(journal, result["decision_events"])
        self.assertEqual(journal[1]["input_messages"][-1]["type"], "human")
        self.assertEqual(journal[2]["input_messages"][-2]["type"], "ai")
        json.dumps(result)

    def test_deadline_does_not_claim_other_agent_decided_or_share_private_text(self):
        first = ScriptedModel(AIMessage(content="Still undecided, private deadline response."))
        second = ScriptedModel(decision("withhold"))
        result = run_game(first, second, max_turns=0)
        self.assertEqual(result["termination_reason"], "max_turns")
        self.assertEqual(result["total_turns"], 0)
        self.assertEqual(result["total_model_calls"], 2)
        for model in (first, second):
            self.assertIn("conversation turn limit", model.requests[0][-1].content)
            self.assertNotIn("other agent has", model.requests[0][-1].content)
        second_input = " ".join(message.content for message in second.requests[0])
        self.assertNotIn("Still undecided", second_input)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["invalid_agents"], [1])
        self.assertEqual(result["agent1_action"], "idle")
        self.assertTrue(result["agent1_defaulted"])
        self.assertFalse(result["agent2_defaulted"])
        self.assertIsNone(result["winner"])
        self.assertIsNone(result["agent1_payoff"])
        self.assertIsNone(result["agent2_payoff"])

    def test_multiple_decisions_are_invalid_and_preserved_without_retry(self):
        ambiguous = AIMessage(content="Two decisions", tool_calls=[
            {"name": "withhold", "args": {"query": "one"}, "id": "one"},
            {"name": "submit_evidence", "args": {"query": "two"}, "id": "two"},
        ])
        first = ScriptedModel(ambiguous)
        second = ScriptedModel(decision("withhold"))
        result = run_game(first, second)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["invalid_agents"], [1])
        self.assertEqual(len(first.requests), 1)
        self.assertEqual(len(result["decision_events"][0]["response_events"][0]["tool_calls"]), 2)
        self.assertIn("Two decisions", json.dumps(result["message_history"]))

    def test_empty_decision_turn_does_not_create_public_speech(self):
        result = run_game(ScriptedModel(decision("submit_evidence")), ScriptedModel(decision("withhold")))
        self.assertEqual(len(result["message_history"]), 2)  # Initial system prompt and kickoff only.
        self.assertEqual([event["public_visibility"] for event in result["decision_events"]], [False, False])

    def test_original_payoffs_are_preserved_for_every_action_pair(self):
        expected = {
            ("withhold", "withhold"): (2, 2, 0),
            ("withhold", "submit_evidence"): (8, 0, 2),
            ("submit_evidence", "withhold"): (0, 8, 1),
            ("submit_evidence", "submit_evidence"): (10, 10, 0),
        }
        for actions, outcomes in expected.items():
            with self.subTest(actions=actions):
                result = run_game(ScriptedModel(decision(actions[0])), ScriptedModel(decision(actions[1])))
                self.assertEqual((result["agent1_payoff"], result["agent2_payoff"], result["winner"]), outcomes)
                self.assertEqual(result["status"], "completed")

    def test_midgame_failure_is_journaled_with_previous_public_input(self):
        first = ScriptedModel(AIMessage(content="I promise cooperation."))
        second = ScriptedModel(RuntimeError("offline simulated failure"))
        journal = []
        with self.assertRaisesRegex(RuntimeError, "offline simulated failure"):
            run_game(first, second, event_callback=journal.append)
        self.assertEqual(len(journal), 2)
        self.assertEqual(journal[-1]["actor_id"], 2)
        self.assertEqual(journal[-1]["input_messages"][-1]["content"], "I promise cooperation.")
        self.assertEqual(journal[-1]["error"]["type"], "RuntimeError")
        json.dumps(journal)


if __name__ == "__main__":
    unittest.main()
