"""Free-only OpenRouter transport with a durable request journal.

No automatic model fallback, paid plugins, or client-side tool execution. Provider
fallbacks within the exact requested free route remain subject to zero price caps.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

BASE_URL = "https://openrouter.ai/api/v1"


class RequestBudgetExhausted(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(self, status, message, model):
        self.status, self.model = status, model
        super().__init__(f"HTTP {status}: {message}")


def free_route(model):
    """Conservative: named :free route, text output, all advertised prices zero."""
    if not isinstance(model, dict):
        return False
    pricing = model.get("pricing", {})
    try:
        return (
            isinstance(model.get("id"), str)
            and model["id"].endswith(":free")
            and "text" in model.get("architecture", {}).get("output_modalities", [])
            and all(Decimal(pricing[k]) == 0 for k in ("prompt", "completion"))
            and all(Decimal(str(v)) == 0 for v in pricing.values())
        )
    except (AttributeError, KeyError, TypeError, InvalidOperation):
        return False


def select_models(catalog):
    eligible, excluded = [], []
    for model in catalog:
        if free_route(model):
            if "tools" in model.get("supported_parameters", []):
                eligible.append(model)
            else:
                excluded.append({"id": model["id"], "reason": "native tool calls not advertised"})
        elif isinstance(model, dict) and isinstance(model.get("pricing"), dict) and model["pricing"].get("prompt") == "0" and model["pricing"].get("completion") == "0":
            excluded.append({"id": model.get("id"), "reason": "not a named :free text route with exclusively zero prices"})
    return sorted(eligible, key=lambda m: m["id"]), excluded


def append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def fetch_metadata(api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    catalog = requests.get(f"{BASE_URL}/models", headers=headers, timeout=30)
    catalog.raise_for_status()
    key = requests.get(f"{BASE_URL}/key", headers=headers, timeout=30)
    key.raise_for_status()
    data = key.json()["data"]
    # Never save a key label, key hash, or authorization header.
    safe_key = {k: data.get(k) for k in ("is_free_tier", "free_model_daily_requests", "usage_daily")}
    return catalog.json()["data"], safe_key


class FreeClient:
    def __init__(self, api_key, models, journal, max_requests=900, interval=3.2, timeout=90, ignored_providers=(), total_timeout=180):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("An OpenRouter API key is required")
        self.api_key = api_key
        self.models = {m["id"]: m for m in models}
        self.journal = Path(journal)
        self.ignored_providers = list(ignored_providers)
        self.invocation_id = str(uuid.uuid4())
        self.max_requests = max_requests
        self.interval, self.timeout = interval, timeout
        self.total_timeout = total_timeout
        self.calls, self.cost, self.next_call = 0, 0.0, 0.0
        self.blocked_reason = None
        self.lock = threading.Lock()

    def _halt(self, reason):
        with self.lock:
            self.blocked_reason = reason
        raise RequestBudgetExhausted(reason)

    def complete(self, model, messages, *, tools=None, temperature=0.7, seed=None, max_tokens=2048, context=None):
        metadata = self.models.get(model)
        if not metadata or not free_route(metadata):
            raise ValueError("Refusing a model absent from the validated free-route catalog")
        payload = {
            "model": model, "messages": messages, "max_tokens": max_tokens,
            "provider": {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0, "request": 0}},
            "stream": False,
        }
        supported = metadata.get("supported_parameters", [])
        if self.ignored_providers:
            payload["provider"]["ignore"] = self.ignored_providers
        if "temperature" in supported:
            payload["temperature"] = temperature
        if seed is not None and "seed" in supported:
            payload["seed"] = seed
        if tools:
            if "tools" not in supported:
                raise ValueError("Native tool calls not advertised")
            payload["tools"] = tools
            if "parallel_tool_calls" in supported:
                payload["parallel_tool_calls"] = False
        with self.lock:
            if self.blocked_reason:
                raise RequestBudgetExhausted(self.blocked_reason)
            if self.calls >= self.max_requests:
                raise RequestBudgetExhausted("Configured free-request budget reached; resume later")
            time.sleep(max(0, self.next_call - time.monotonic()))
            self.next_call = time.monotonic() + self.interval
            self.calls += 1
            request_number = self.calls
        record = {"request_id": str(uuid.uuid4()), "invocation_id": self.invocation_id,
                  "request_number": request_number, "timestamp": time.time(), "context": context, "request": payload}
        append_jsonl(self.journal, {**record, "event": "request_started"})
        started = time.monotonic()
        try:
            response = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "X-OpenRouter-Title": "Dilemma Bench research"},
                json=payload, timeout=(15, min(self.timeout, self.total_timeout)), stream=True,
            )
            try:
                # The API sends whitespace keepalives for non-streaming requests.
                # A socket read timeout alone can therefore wait indefinitely.
                # Read bytes as they arrive so keepalives cannot reset this deadline.
                raw_body = bytearray()
                for chunk in response.iter_content(chunk_size=1):
                    if time.monotonic() - started > self.total_timeout:
                        raise requests.Timeout("Total response deadline exceeded")
                    raw_body.extend(chunk)
                if time.monotonic() - started > self.total_timeout:
                    raise requests.Timeout("Total response deadline exceeded")
                try:
                    body = json.loads(raw_body)
                except (ValueError, UnicodeDecodeError):
                    body = {"error": {"message": "Non-JSON provider response"}}
            finally:
                response.close()
            # Provider error strings should never be able to echo our credential.
            body = json.loads(json.dumps(body).replace(self.api_key, "[REDACTED]"))
            append_jsonl(self.journal, {**record, "event": "request_finished", "http_status": response.status_code, "response": body})
            if not isinstance(body, dict):
                raise ProviderError(502, "Response body must be an object", model)
            error = body.get("error")
            if response.status_code != 200 or error:
                error = error if isinstance(error, dict) else {"message": str(error)}
                status = error.get("code", response.status_code)
                try:
                    status = int(status)
                except (TypeError, ValueError):
                    status = response.status_code
                msg = str(error.get("message", "Request failed"))[:500]
                upstream = isinstance(error.get("metadata"), dict) and bool(error["metadata"].get("provider_name"))
                if (status in (401, 402) and not upstream) or (status == 429 and any(s in msg.lower() for s in ("daily", "per-day", "free-models-per-day"))):
                    self._halt(f"OpenRouter blocked further requests (HTTP {status}): {msg}")
                raise ProviderError(status, msg, model)
            usage = body.get("usage") or {}
            if not isinstance(usage, dict):
                self._halt("Invalid usage metadata; cannot verify reported cost")
            if usage.get("is_byok") is True:
                self._halt("BYOK provider used despite free route; stop and exclude that provider before continuing")
            try:
                cost = Decimal(str(usage.get("cost") or 0))
                if not cost.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                self._halt("Invalid reported cost; stopped")
            with self.lock:
                self.cost += float(cost)
            if cost > 0:
                self._halt("Nonzero cost reported despite free route and zero price caps; stopped")
            if not body.get("choices"):
                raise ProviderError(502, "Missing response choices", model)
            return body
        except requests.RequestException as exc:
            append_jsonl(self.journal, {**record, "event": "request_failed", "error_type": type(exc).__name__})
            raise ProviderError(0, type(exc).__name__, model) from None


class FreeChatModel:
    """Minimal LangGraph-compatible adapter retaining the entire provider response."""
    def __init__(self, client, model, seed, temperature=0.7, max_tokens=2048, context=None):
        self.client, self.model, self.seed = client, model, seed
        self.temperature, self.max_tokens, self.context = temperature, max_tokens, context
        self.tools = None

    def bind_tools(self, tools, **kwargs):
        bound = copy.copy(self)
        bound.tools = [convert_to_openai_tool(tool) for tool in tools]
        return bound

    def invoke(self, messages):
        roles = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
        serialized = [{"role": roles[m.type], "content": m.content} for m in messages]
        body = self.client.complete(self.model, serialized, tools=self.tools,
                                    temperature=self.temperature, seed=self.seed,
                                    max_tokens=self.max_tokens, context=self.context)
        try:
            raw = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(502, "Missing assistant response message", self.model) from None
        if not isinstance(raw, dict):
            raise ProviderError(502, "Assistant response message must be an object", self.model)
        valid, invalid = [], []
        calls = raw.get("tool_calls") or []
        if not isinstance(calls, list):
            calls = [calls]
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else None
            try:
                if not isinstance(call, dict) or not isinstance(fn, dict):
                    raise ValueError("Tool call and function must be objects")
                if not isinstance(fn.get("name"), str) or not fn["name"]:
                    raise ValueError("Tool name must be a nonempty string")
                if not isinstance(call.get("id"), str) or not call["id"]:
                    raise ValueError("Tool call ID must be a nonempty string")
                args = json.loads(fn["arguments"])
                if not isinstance(args, dict):
                    raise ValueError("Arguments must be an object")
                valid.append({"name": fn["name"], "args": args, "id": call["id"]})
            except (KeyError, ValueError, TypeError):
                fn = fn if isinstance(fn, dict) else {}
                name = fn.get("name")
                arguments = fn.get("arguments")
                call_id = call.get("id") if isinstance(call, dict) else None
                invalid.append({
                    "name": name if isinstance(name, str) else None,
                    "args": arguments if isinstance(arguments, str) else json.dumps(arguments, default=str),
                    "id": call_id if isinstance(call_id, str) else None,
                    "error": "Malformed tool call",
                })
        return AIMessage(content=raw.get("content") or "", tool_calls=valid,
                         invalid_tool_calls=invalid, response_metadata={"openrouter": body})
