"""Offline transport checks against the installed LangChain and real game graph."""
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.graph import play_match
from research.openrouter import FreeChatModel, FreeClient, ProviderError, RequestBudgetExhausted, free_route, select_models


def model_metadata(model_id="test/model:free"):
    return {
        "id": model_id,
        "architecture": {"output_modalities": ["text"]},
        "pricing": {"prompt": "0", "completion": "0", "request": "0"},
        "supported_parameters": ["tools", "temperature", "seed", "parallel_tool_calls"],
    }


def response_body(content="hello", calls=None, cost=0):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"id": "response-id", "choices": [{"message": message, "finish_reason": "stop"}], "usage": {"cost": cost}}


def tool_call(name="withhold", args='{"query":"private"}', call_id="call-id"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def http_response(body, status=200):
    raw = json.dumps(body).encode()
    return Mock(status_code=status, iter_content=Mock(side_effect=lambda **kwargs: iter(bytes([byte]) for byte in raw)))


class FreeRouteTests(unittest.TestCase):
    def test_only_explicit_completely_zero_priced_text_routes_pass(self):
        self.assertTrue(free_route(model_metadata()))
        bad_models = [None, {}, {"id": None}, model_metadata("test/paid")]
        for field, value in [("pricing", None), ("architecture", None), ("pricing", {"prompt": "0"}),
                             ("pricing", {"prompt": "0", "completion": "0", "request": "0.001"}),
                             ("pricing", {"prompt": "NaN", "completion": "0"}),
                             ("architecture", {"output_modalities": ["image"]})]:
            metadata = model_metadata()
            metadata[field] = value
            bad_models.append(metadata)
        for metadata in bad_models:
            with self.subTest(metadata=metadata):
                self.assertFalse(free_route(metadata))
        text_only = model_metadata("test/no-tools:free")
        text_only["supported_parameters"] = []
        eligible, excluded = select_models([model_metadata(), text_only] + bad_models)
        self.assertEqual([m["id"] for m in eligible], ["test/model:free"])
        self.assertIn("test/no-tools:free", [m["id"] for m in excluded])


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / "requests.jsonl"
        self.client = FreeClient("secret-test-key", [model_metadata()], self.journal, max_requests=2, interval=0)

    def test_zero_caps_durable_redacted_journal_and_request_limit(self):
        body = response_body("provider accidentally echoed secret-test-key")
        with patch("research.openrouter.requests.post", return_value=http_response(body)) as post, patch("research.openrouter.os.fsync") as fsync:
            self.client.complete("test/model:free", [{"role": "user", "content": "hello"}], seed=3)
            self.client.complete("test/model:free", [])
            with self.assertRaises(RequestBudgetExhausted):
                self.client.complete("test/model:free", [])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(fsync.call_count, 4)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertNotIn("models", payload)
        text = self.journal.read_text()
        self.assertNotIn("secret-test-key", text)
        self.assertNotIn("Authorization", text)
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([row["event"] for row in rows], ["request_started", "request_finished"] * 2)
        self.assertEqual(rows[0]["request_id"], rows[1]["request_id"])
        self.assertEqual(rows[2]["request_id"], rows[3]["request_id"])
        self.assertNotEqual(rows[0]["request_id"], rows[2]["request_id"])
        self.assertEqual({row["invocation_id"] for row in rows}, {self.client.invocation_id})
        self.assertIn("[REDACTED]", rows[1]["response"]["choices"][0]["message"]["content"])

    def test_nonzero_cost_latches_halt_before_any_further_request(self):
        with patch("research.openrouter.requests.post", return_value=http_response(response_body(cost=0.01))) as post:
            for _ in range(2):
                with self.assertRaises(RequestBudgetExhausted):
                    self.client.complete("test/model:free", [])
        self.assertEqual(post.call_count, 1)

    def test_ignored_providers_are_sent_and_journaled_with_zero_price_caps(self):
        excluded = ["google-ai-studio", "google-vertex"]
        client = FreeClient("secret-test-key", [model_metadata()], self.journal,
                            interval=0, ignored_providers=excluded)
        with patch("research.openrouter.requests.post", return_value=http_response(response_body())) as post:
            client.complete("test/model:free", [])
        provider = post.call_args.kwargs["json"]["provider"]
        self.assertEqual(provider["ignore"], excluded)
        self.assertEqual(provider["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertTrue(provider["require_parameters"])
        rows = [json.loads(line) for line in self.journal.read_text().splitlines()]
        self.assertTrue(all(row["request"]["provider"]["ignore"] == excluded for row in rows))

    def test_upstream_auth_and_payment_errors_are_local_not_global_halts(self):
        for status in (401, 402):
            with self.subTest(status=status):
                client = FreeClient("secret-test-key", [model_metadata()], self.journal, interval=0)
                body = {"error": {"code": status, "message": "Upstream account unavailable",
                                  "metadata": {"provider_name": "Google AI Studio"}}}
                with patch("research.openrouter.requests.post", side_effect=[http_response(body, status), http_response(response_body())]) as post:
                    with self.assertRaises(ProviderError) as raised:
                        client.complete("test/model:free", [])
                    self.assertEqual(raised.exception.status, status)
                    self.assertIsNone(client.blocked_reason)
                    self.assertEqual(client.complete("test/model:free", [])["id"], "response-id")
                self.assertEqual(post.call_count, 2)

    def test_byok_usage_halts_even_when_reported_cost_is_zero(self):
        body = response_body(cost=0)
        body["usage"]["is_byok"] = True
        with patch("research.openrouter.requests.post", return_value=http_response(body)) as post:
            for _ in range(2):
                with self.assertRaisesRegex(RequestBudgetExhausted, "BYOK"):
                    self.client.complete("test/model:free", [])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.client.cost, 0)
        rows = [json.loads(line) for line in self.journal.read_text().splitlines()]
        self.assertTrue(rows[-1]["response"]["usage"]["is_byok"])

    def test_refuses_unknown_or_paid_route_before_network(self):
        with patch("research.openrouter.requests.post") as post:
            for model in ["test/model", "other/free:free"]:
                with self.assertRaises(ValueError):
                    self.client.complete(model, [])
        post.assert_not_called()
        self.assertFalse(self.journal.exists())

    def test_network_failure_has_no_secret_exception_text_or_retry(self):
        with patch("research.openrouter.requests.post", side_effect=requests.Timeout("secret-test-key")) as post:
            with self.assertRaises(ProviderError) as raised:
                self.client.complete("test/model:free", [])
        self.assertEqual(post.call_count, 1)
        self.assertNotIn("secret-test-key", str(raised.exception))
        self.assertNotIn("secret-test-key", self.journal.read_text())
        self.assertEqual(json.loads(self.journal.read_text().splitlines()[-1])["event"], "request_failed")

    def test_keepalives_cannot_extend_response_deadline(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = iter([b" ", b" ", b" "])
        # Three pacing clock reads, one start, then each byte arriving at 100s.
        with patch("research.openrouter.time.monotonic", side_effect=[0, 0, 0, 0, 100, 200]), patch("research.openrouter.requests.post", return_value=response):
            with self.assertRaises(ProviderError):
                self.client.complete("test/model:free", [])
        response.close.assert_called_once()
        self.assertEqual(json.loads(self.journal.read_text().splitlines()[-1])["error_type"], "Timeout")

    def test_daily_limit_error_halts_even_when_status_code_is_string(self):
        error = {"error": {"code": "429", "message": "Free-models-per-day limit reached"}}
        with patch("research.openrouter.requests.post", return_value=http_response(error, 429)) as post:
            for _ in range(2):
                with self.assertRaises(RequestBudgetExhausted):
                    self.client.complete("test/model:free", [])
        self.assertEqual(post.call_count, 1)

    def test_actual_game_graph_smoke_via_mocked_http(self):
        first = FreeChatModel(self.client, "test/model:free", seed=10)
        second = FreeChatModel(self.client, "test/model:free", seed=11)
        responses = [
            http_response(response_body("Public authored promise", [tool_call("submit_evidence", args='{"query":"tool-secret-sentinel"}', call_id="first")])),
            http_response(response_body(None, [tool_call("withhold", call_id="second")])),
        ]
        with patch("research.openrouter.requests.post", side_effect=responses) as post, redirect_stdout(io.StringIO()):
            result = asyncio.run(play_match(first, second))
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["agent1_payoff"], result["agent2_payoff"]), (0, 8))
        self.assertEqual(result["decision_events"][0]["assistant_text"], "Public authored promise")
        self.assertEqual(result["decision_events"][0]["response_events"][0]["response_metadata"]["openrouter"]["id"], "response-id")
        second_request = post.call_args.kwargs["json"]
        self.assertIn("Public authored promise", json.dumps(second_request["messages"]))
        self.assertNotIn("tool-secret-sentinel", json.dumps(second_request["messages"]))
        self.assertEqual(second_request["parallel_tool_calls"], False)
        self.assertEqual(second_request["seed"], 11)
        self.assertEqual(len(second_request["tools"]), 2)

    def test_malformed_tool_data_remains_invalid_evidence_in_langchain(self):
        malformed = ["not-an-object", {"function": None}, tool_call(args={"query": "already parsed"}),
                     tool_call(name=123), tool_call(args="[]"), tool_call(args="not JSON"), tool_call(call_id=None)]
        for call in malformed:
            with self.subTest(call=call):
                fake_client = Mock()
                fake_client.complete.return_value = response_body(calls=[call])
                response = FreeChatModel(fake_client, "test/model:free", seed=1).invoke([])
                self.assertEqual(response.tool_calls, [])
                self.assertEqual(len(response.invalid_tool_calls), 1)
                self.assertEqual(response.response_metadata["openrouter"]["choices"][0]["message"]["tool_calls"], [call])

    def test_mixed_valid_and_invalid_decisions_do_not_execute_valid_one(self):
        first_client, second_client = Mock(), Mock()
        first_client.complete.return_value = response_body(calls=[tool_call(), tool_call(args="bad")])
        second_client.complete.return_value = response_body(calls=[tool_call()])
        with redirect_stdout(io.StringIO()):
            result = asyncio.run(play_match(FreeChatModel(first_client, "test/model:free", 1), FreeChatModel(second_client, "test/model:free", 2)))
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["agent1_action"], "idle")
        self.assertEqual(result["invalid_agents"], [1])
        self.assertEqual(first_client.complete.call_count, 1)


if __name__ == "__main__":
    unittest.main()
