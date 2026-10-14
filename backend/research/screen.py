"""Run: python -m research.screen --run-dir research_data/free-screen --max-games 156.

Catalog and schedule are snapshotted; rerunning the same command resumes without
rerunning completed games. Requests/events are journaled before database writes.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import uuid

from dotenv import load_dotenv
from agent.graph import get_game_prompt, play_match
from research.database import ResearchStore
from research.judge import judge_game
from research.openrouter import (FreeChatModel, FreeClient, ProviderError,
    RequestBudgetExhausted, append_jsonl, fetch_metadata, select_models)


def save_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
    temp.replace(path)


def schedule(model_ids, seed=20261014, repetitions=2):
    """Circle round robin; each pair repeats with opposite speaking order."""
    ring = list(sorted(model_ids))
    random.Random(seed).shuffle(ring)
    if len(ring) % 2:
        ring.append(None)
    first = []
    for round_index in range(len(ring) - 1):
        for i in range(len(ring) // 2):
            a, b = ring[i], ring[-i - 1]
            if a is not None and b is not None:
                first.append((a, b) if (round_index + i) % 2 == 0 else (b, a))
        ring = [ring[0], ring[-1], *ring[1:-1]]
    return [{"game_id": f"game-{rep:02d}-{i:04d}", "models": list(pair if rep % 2 == 0 else pair[::-1]),
             "seed": seed + rep * len(first) + i}
            for rep in range(repetitions) for i, pair in enumerate(first)]


def canonical_game(result):
    # Use the explicit visibility marker, never raw assistant/tool output.
    return {"setting": get_game_prompt(), "participant_ids": [1, 2],
            "public_messages": [{"turn": e["event_index"], "actor_id": e["actor_id"], "content": e["assistant_text"]}
                                for e in result.get("decision_events", []) if e.get("public_visibility") is True],
            "actions": {1: result.get("agent1_action"), 2: result.get("agent2_action")}}


def request_accounting(run_dir):
    """Reconstruct cumulative usage across resumes from the durable journal."""
    totals = Counter()
    cost = Decimal(0)
    seen = set()
    path = run_dir / "requests.jsonl"
    if path.exists():
        with path.open() as journal:
            for line in journal:
                try:
                    record = json.loads(line)
                except ValueError:
                    totals["journal_parse_errors"] += 1
                    continue
                if not isinstance(record, dict):
                    totals["journal_parse_errors"] += 1
                    continue
                event = record.get("event")
                identity = (record.get("request_id"), event)
                if identity[0] and identity in seen:
                    continue
                if identity[0]:
                    seen.add(identity)
                if event in ("request_started", "request_finished", "request_failed"):
                    totals[event] += 1
                if event != "request_finished":
                    continue
                response = record.get("response")
                usage = response.get("usage") if isinstance(response, dict) else None
                if not isinstance(usage, dict) or usage.get("cost") is None:
                    totals["cost_unreported_responses"] += 1
                    continue
                try:
                    value = Decimal(str(usage["cost"]))
                    if not value.is_finite():
                        raise InvalidOperation
                    cost += value
                except (InvalidOperation, ValueError):
                    totals["cost_unreported_responses"] += 1
    return {"reported_cost_usd": float(cost), **dict(totals)}


def summarize(run_dir, manifest):
    counts = {m["id"]: Counter() for m in manifest["models"]}
    examples = []
    completed = 0
    scheduled_ids = {entry["game_id"] for entry in manifest["schedule"]}
    completed_ids, judged_ids, judgment_error_ids = set(), set(), set()
    for path in sorted((run_dir / "games").glob("*.json")):
        game = json.loads(path.read_text())
        for model in game["models"]:
            counts[model]["games_attempted"] += 1
            counts[model]["games_" + game["status"]] += 1
        for event in game.get("decision_events", []):
            model = game["models"][int(event["actor_id"]) - 1]
            counts[model]["model_calls"] += 1
        if game["status"] in ("completed", "invalid"):
            completed += 1
            completed_ids.add(game["game_id"])
        judge_path = run_dir / "judgments" / path.name
        if judge_path.exists():
            judgment = json.loads(judge_path.read_text())
            if judgment["judge_status"] == "ok":
                if game["game_id"] in completed_ids:
                    judged_ids.add(game["game_id"])
                for claim in judgment["claims"]:
                    model = game["models"][int(claim["actor_id"]) - 1]
                    counts[model][claim["status"]] += 1
                    if claim["status"] == "broken":
                        examples.append({"game_id": game["game_id"], "model": model, **claim})
            else:
                judgment_error_ids.add(game["game_id"])
                for model in game["models"]:
                    counts[model]["judge_errors"] += 1
    result = {"run_id": manifest["run_id"], "updated_at": time.time(),
              "completed_or_invalid_games": completed,
              "games_complete": scheduled_ids.issubset(completed_ids),
              "analysis_complete": scheduled_ids.issubset(completed_ids & judged_ids),
              "successfully_judged_games": len(judged_ids),
              "missing_judgments": len(completed_ids - judged_ids - judgment_error_ids),
              "failed_judgments": len(judgment_error_ids),
              "request_accounting": request_accounting(run_dir),
              "scheduled_games": len(manifest["schedule"]), "models": counts,
              "exclusions": manifest["excluded"], "availability": manifest.get("availability", {}), "broken_promise_examples": examples,
              "caveat": "LLM-judged latest public commitments; preliminary labels require semantic audit. Counts are participant observations, not independent trials. API routes do not establish local checkpoint equivalence."}
    save_json(run_dir / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-games", type=int, default=156, help="Maximum schedule entries to attempt this invocation")
    parser.add_argument("--max-requests", type=int, default=900)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--judge-model", default="google/gemma-4-31b-it:free")
    parser.add_argument("--ignore-provider", action="append", default=[], help="Exclude a provider, e.g. to avoid account-level BYOK fallback")
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--retry-errors", action="store_true", help="Archive and retry failed games/judgments and refresh provider preflight")
    args = parser.parse_args()
    if args.max_requests < 1 or args.max_games < 0 or args.repetitions < 1 or args.max_turns < 1:
        parser.error("Request budget, repetitions and turns must be positive; games nonnegative")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("games", "judgments"):
        (run_dir / name).mkdir(exist_ok=True)
    # Prevent two runs sharing a schedule/journal and consuming quotas twice.
    import fcntl
    lockfile = (run_dir / ".lock").open("w")
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("This run directory already has an active worker")
    catalog, key = fetch_metadata(os.environ["OPENROUTER_API_KEY"])
    live_models, excluded = select_models(catalog)
    path = run_dir / "manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text())
    else:
        if len(live_models) < 2:
            raise RuntimeError("Fewer than two free native-tool models are available")
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        manifest = {"schema_version": 1, "run_id": str(uuid.uuid4()), "created_at": time.time(),
                    "git_sha": git_sha, "git_worktree_modified": True,
                    "prompt": get_game_prompt(), "prompt_sha256": hashlib.sha256(get_game_prompt().encode()).hexdigest(),
                    "models": live_models, "excluded": excluded, "key_at_start": key,
                    "settings": {k: getattr(args, k) for k in ("max_turns", "max_tokens", "temperature", "seed", "repetitions", "judge_model", "ignore_provider")},
                    "schedule": schedule([m["id"] for m in live_models], args.seed, args.repetitions),
                    "payoffs": {"CC": [2, 2], "CD": [8, 0], "DC": [0, 8], "DD": [10, 10]},
                    "status": "planned"}
        save_json(path, manifest)
        save_json(run_dir / "catalog.json", catalog)
    settings = manifest["settings"]
    if manifest["prompt_sha256"] != hashlib.sha256(get_game_prompt().encode()).hexdigest():
        raise RuntimeError("Game prompt changed; start a new run directory")
    print(json.dumps({"run_id": manifest["run_id"], "free_models": len(live_models), "excluded": excluded,
                      "scheduled_games": len(manifest["schedule"]), "quota": key.get("free_model_daily_requests")}), flush=True)
    if args.catalog_only:
        return
    if settings["judge_model"] not in {m["id"] for m in live_models}:
        raise RuntimeError("Configured judge is no longer a validated free route; use a new run with an available judge")
    # Save code and library versions, including uncommitted edits, for each invocation.
    from importlib.metadata import distributions
    backend = Path(__file__).resolve().parents[1]
    source_paths = [Path("agent/graph.py"), *[Path("research") / name for name in ("screen.py", "openrouter.py", "judge.py", "database.py")]]
    hashes = {str(p): hashlib.sha256((backend / p).read_bytes()).hexdigest() for p in source_paths}
    source_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    source_dir = run_dir / "source" / source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    for p in source_paths:
        (source_dir / p.parent).mkdir(exist_ok=True)
        shutil.copy2(backend / p, source_dir / p)
    save_json(source_dir / "versions.json", {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]})
    manifest.setdefault("source_versions", {})[source_id] = hashes
    remaining = (key.get("free_model_daily_requests") or {}).get("remaining", args.max_requests)
    budget = min(args.max_requests, remaining)
    client = FreeClient(os.environ["OPENROUTER_API_KEY"], live_models, run_dir / "requests.jsonl", max_requests=budget,
                        ignored_providers=settings.get("ignore_provider", []))
    store = None
    db_errors = []
    if not args.no_db:
        try:
            store = ResearchStore()
        except Exception as exc:
            db_errors.append({"kind": "initial_connection", "error_type": type(exc).__name__})
            print(json.dumps({"event": "local_only", **db_errors[-1]}), flush=True)
    def sync(kind, record, game_id=None):
        if store:
            try:
                if kind == "run":
                    store.put_run(manifest["run_id"], record)
                else:
                    getattr(store, f"put_{kind}")(manifest["run_id"], game_id, record)
            except Exception as exc:
                db_errors.append({"kind": kind, "game_id": game_id, "error_type": type(exc).__name__})
                print(json.dumps(db_errors[-1]), flush=True)
    # Replay local artifacts to DB on every resume, including formerly failed writes.
    sync("run", manifest)
    for kind, folder in (("game", "games"), ("judgment", "judgments")):
        for saved in (run_dir / folder).glob("*.json"):
            sync(kind, json.loads(saved.read_text()), saved.stem)
    manifest["status"] = "running"
    save_json(path, manifest)
    sync("run", manifest)
    attempted = 0
    model_errors = Counter()
    stop_reason = None
    try:
        availability = manifest.setdefault("availability", {})
        # Check every named free route directly: a failed first player must not
        # prevent us from discovering whether its scheduled opponent is usable.
        from agent.graph import tools as game_tools
        from langchain_core.utils.function_calling import convert_to_openai_tool
        tool_specs = [convert_to_openai_tool(tool) for tool in game_tools]
        for model in manifest["models"]:
            model_id = model["id"]
            if model_id in availability and not args.retry_errors:
                continue
            if model_id not in client.models:
                availability[model_id] = {"status": "unavailable", "reason": "route no longer free/available"}
                continue
            try:
                response = client.complete(model_id, [{"role": "user", "content": "API compatibility check: call withhold with query set to check. This is not a game."}],
                                           tools=tool_specs, temperature=0, max_tokens=256, context={"kind": "preflight"})
                availability[model_id] = {"status": "available", "native_call_observed": bool(response["choices"][0]["message"].get("tool_calls")), "checked_at": time.time()}
            except ProviderError as exc:
                availability[model_id] = {"status": "unavailable", "reason": str(exc), "checked_at": time.time()}
            save_json(path, manifest)
            print(json.dumps({"event": "preflight", "model": model_id, **availability[model_id]}), flush=True)
        if availability.get(settings["judge_model"], {}).get("status") != "available":
            raise RequestBudgetExhausted("Configured free judge is unavailable; choose an available judge in a new run")
        for entry in manifest["schedule"]:
            game_id = entry["game_id"]
            game_path = run_dir / "games" / f"{game_id}.json"
            judge_path = run_dir / "judgments" / f"{game_id}.json"
            if args.retry_errors:
                archive = run_dir / "previous_attempts"
                for prior in (game_path, judge_path):
                    if prior.exists():
                        record = json.loads(prior.read_text())
                        if record.get("status") == "provider_error" or record.get("judge_status") == "error":
                            archive.mkdir(exist_ok=True)
                            prior.replace(archive / f"{prior.parent.name}-{prior.stem}-{time.time_ns()}.json")
            if game_path.exists():
                game = json.loads(game_path.read_text())
            else:
                if attempted >= args.max_games:
                    stop_reason = "invocation_game_limit"
                    break
                if any(m not in client.models for m in entry["models"]):
                    # Record a recoverable skip separately; don't claim a game happened.
                    append_jsonl(run_dir / "skips.jsonl", {**entry, "reason": "route no longer free/available", "timestamp": time.time()})
                    continue
                if any(availability.get(m, {}).get("status") != "available" for m in entry["models"]):
                    append_jsonl(run_dir / "skips.jsonl", {**entry, "reason": "provider preflight unavailable", "timestamp": time.time()})
                    continue
                if any(model_errors[m] >= 2 for m in entry["models"]):
                    append_jsonl(run_dir / "skips.jsonl", {**entry, "reason": "provider repeatedly unavailable this invocation", "timestamp": time.time()})
                    continue
                attempted += 1
                attempt_id = str(uuid.uuid4())
                print(json.dumps({"event": "game_started", **entry, "requests": client.calls}), flush=True)
                events = []
                def capture(event):
                    events.append(event)
                    append_jsonl(run_dir / "events.jsonl", {"game_id": game_id, "attempt_id": attempt_id, "invocation_id": client.invocation_id, **event})
                models = [FreeChatModel(client, m, entry["seed"], settings["temperature"], settings["max_tokens"],
                                       context={"game_id": game_id, "attempt_id": attempt_id, "actor_id": i + 1, "kind": "game"})
                          for i, m in enumerate(entry["models"])]
                try:
                    result = asyncio.run(play_match(*models, max_turns=settings["max_turns"], event_callback=capture))
                    game = {**entry, **result, "created_at": time.time(), "source_id": source_id, "attempt_id": attempt_id}
                except RequestBudgetExhausted:
                    # Partial events are durable, but resumption must restart this game.
                    raise
                except Exception as exc:
                    if isinstance(exc, ProviderError):
                        model_errors[exc.model] += 1
                    game = {**entry, "status": "provider_error", "created_at": time.time(), "source_id": source_id, "attempt_id": attempt_id,
                            "decision_events": events, "error": {"type": type(exc).__name__, "message": str(exc)[:500]}}
                save_json(game_path, game)
                sync("game", game, game_id)
                print(json.dumps({"event": "game_finished", "game_id": game_id, "status": game["status"], "requests": client.calls}), flush=True)
            if game["status"] in ("completed", "invalid") and not judge_path.exists():
                budget_error = []
                def completion(messages):
                    try:
                        response = client.complete(settings["judge_model"], messages, temperature=0, max_tokens=4096,
                                                   context={"kind": "judge", "game_id": game_id})
                        return response["choices"][0]["message"].get("content") or ""
                    except RequestBudgetExhausted as exc:
                        budget_error.append(exc)
                        raise
                judgment = judge_game(canonical_game(game), completion)
                if budget_error:
                    raise budget_error[0]
                judgment.update({"game_id": game_id, "judge_model": settings["judge_model"], "created_at": time.time(), "source_id": source_id})
                save_json(judge_path, judgment)
                sync("judgment", judgment, game_id)
                print(json.dumps({"event": "judged", "game_id": game_id, "judge_status": judgment["judge_status"], "coverage": judgment["coverage"]}), flush=True)
            summarize(run_dir, manifest)
    except (RequestBudgetExhausted, KeyboardInterrupt) as exc:
        stop_reason = str(exc) or "interrupted"
    except Exception as exc:
        stop_reason = "Unexpected failure: " + type(exc).__name__
        raise
    finally:
        summary = summarize(run_dir, manifest)
        complete = summary["analysis_complete"]
        manifest.update({"status": "complete" if complete else "partial", "stop_reason": stop_reason,
                         "games_complete": summary["games_complete"], "analysis_complete": complete,
                         "last_invocation_requests": client.calls,
                         "last_invocation_reported_cost_usd": client.cost,
                         "reported_cost_usd": summary["request_accounting"]["reported_cost_usd"], "db_errors": db_errors,
                         "updated_at": time.time()})
        save_json(path, manifest)
        sync("run", manifest)
        if store:
            store.close()
        print(json.dumps({"event": "run_stopped", "reason": stop_reason, "requests": client.calls,
                          "reported_cost_usd": manifest["reported_cost_usd"], "models": summary["models"]}), flush=True)


if __name__ == "__main__":
    main()
