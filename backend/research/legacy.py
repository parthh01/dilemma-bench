"""Label a seeded historical sample using public prefixes and a free judge.

Run from backend: python -m research.legacy --limit 20 --run-dir research_data/legacy-labels
This reads an existing export, never queries or updates historical/Elo tables.
Historical visibility is inferred conservatively from termination markers; the
resulting labels need semantic audit and cannot recover original activations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import time
import uuid

from dotenv import load_dotenv

from research.database import ResearchStore
from research.judge import ACTIONS, judge_game, public_context
from research.openrouter import FreeClient, RequestBudgetExhausted, fetch_metadata, free_route


BACKEND = Path(__file__).resolve().parents[1]


def legacy_public_game(record):
    """Convert an export record without exposing private post-decision text.

    Source rows are sorted as in database.export_legacy_games. Turn IDs are
    positions in that ordering, with a separate map back to transcript rows.
    A later system message always ends the safe prefix, even when its exact
    wording is unfamiliar. Defaulted or unverified actions are never scored.
    """
    if not isinstance(record, dict) or record.get("record_type") != "legacy_match":
        raise ValueError("Expected a legacy_match export record")
    match, agents, transcripts = record.get("match"), record.get("agents"), record.get("transcripts")
    if not isinstance(match, dict) or not isinstance(agents, dict) or not isinstance(transcripts, list):
        raise ValueError("Historical match, agents, or transcripts are missing")
    match_id = match.get("id")
    if not isinstance(match_id, str) or not match_id or not all(c.isalnum() or c in "-_" for c in match_id):
        raise ValueError("Historical match needs a filename-safe string ID")
    for row in transcripts:
        if not isinstance(row, dict) or isinstance(row.get("order"), bool) or not isinstance(row.get("order"), int):
            raise ValueError("Historical transcripts need integer order values")
        if not isinstance(row.get("message"), str):
            raise ValueError("Historical transcript text must be a string")
    rows = sorted(transcripts, key=lambda row: (row["order"], row.get("created_at") or "", str(row.get("id", ""))))
    if not rows or rows[0].get("agent_id") != 0 or not rows[0]["message"].strip():
        raise ValueError("Historical transcript needs an initial system setting")
    public_messages, source_map = [], []
    cutoff = {"reason": "end_of_transcript", "source_position": len(rows)}
    for position, row in enumerate(rows[1:], 1):
        content = row["message"]
        if content.strip().casefold() == "action completed":
            cutoff = {"reason": "action_acknowledgement", "source_position": position}
            break
        if row.get("agent_id") == 0:
            cutoff = {"reason": "later_system_message", "source_position": position}
            break
        actor = row.get("agent_id")
        if isinstance(actor, bool) or actor not in (1, 2):
            continue
        if not content.strip() or content.strip() == "_":
            continue
        public_messages.append({"turn": position, "actor_id": actor, "content": content})
        source_map.append({"turn": position, "transcript_id": row.get("id"), "source_order": row["order"]})
    models = []
    actions, defaults, stored_actions = {}, {}, {}
    for actor in (1, 2):
        agent = agents.get(f"agent{actor}")
        if not isinstance(agent, dict) or not isinstance(agent.get("name"), str) or not agent["name"].strip():
            raise ValueError("Historical model name missing")
        models.append(agent["name"])
        default = match.get(f"agent{actor}_default")
        action = match.get(f"agent{actor}_action")
        defaults[str(actor)], stored_actions[str(actor)] = default, action
        actions[actor] = action if default is False and isinstance(action, str) and action in ACTIONS else None
    game = {
        "game_id": "legacy-" + match_id, "source_match_id": match_id,
        "models": models, "status": "completed" if all(actions.values()) else "invalid",
        "setting": rows[0]["message"], "participant_ids": [1, 2],
        "public_messages": public_messages, "actions": actions,
        "source_agent_ids": [agents[f"agent{actor}"].get("id") for actor in (1, 2)],
        "source_created_at": match.get("created_at"),
        "default_flags": defaults, "stored_actions": stored_actions,
        "public_source_map": source_map, "public_prefix_cutoff": cutoff,
        "provenance": record.get("provenance", {}),
        "visibility_caveat": "Public visibility inferred from legacy termination markers; unavailable private assistant/tool metadata cannot be reconstructed.",
    }
    public_context(game)
    return game


def sample_legacy_games(records, *, limit=20, seed=20261014, include_invalid=False):
    """Shuffle all eligible match IDs, without selecting on promise content."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("Sample limit must be a nonnegative integer")
    eligible, exclusions, seen = [], Counter(), set()
    source_count = 0
    for record in records:
        source_count += 1
        try:
            game = legacy_public_game(record)
        except (ValueError, TypeError, KeyError):
            exclusions["malformed_or_missing_initial_setting"] += 1
            continue
        if game["source_match_id"] in seen:
            raise ValueError("Duplicate historical match ID")
        seen.add(game["source_match_id"])
        if not include_invalid and game["status"] != "completed":
            exclusions["defaulted_missing_or_invalid_action"] += 1
            continue
        eligible.append(game)
    eligible.sort(key=lambda game: game["source_match_id"])
    random.Random(seed).shuffle(eligible)
    return {
        "games": eligible[:limit], "source_games": source_count,
        "eligible_games": len(eligible), "exclusions": dict(exclusions),
        "sampling": "seeded_shuffle_of_all_eligible_match_ids_no_promise_filter",
    }


def read_export(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize_legacy(run_dir, manifest):
    counts = defaultdict(Counter)
    judged_games = judge_errors = 0
    for entry in manifest["selection"]:
        game = json.loads((run_dir / "games" / f"{entry['game_id']}.json").read_text())
        for model in game["models"]:
            counts[model]["selected_participant_observations"] += 1
        path = run_dir / "judgments" / f"{game['game_id']}.json"
        if not path.exists():
            continue
        judgment = json.loads(path.read_text())
        if judgment["judge_status"] != "ok":
            judge_errors += 1
            for model in game["models"]:
                counts[model]["judge_errors"] += 1
            continue
        judged_games += 1
        for claim in judgment["claims"]:
            counts[game["models"][int(claim["actor_id"]) - 1]][claim["status"]] += 1
    summary = {
        "run_id": manifest["run_id"], "selected_games": len(manifest["selection"]),
        "judged_games": judged_games, "judge_error_games": judge_errors,
        "unjudged_games": len(manifest["selection"]) - judged_games - judge_errors,
        "models": dict(counts), "source_export_sha256": manifest["source_export_sha256"],
        "caveat": "Historical API-game labels with inferred public visibility, not J-lens evidence. Model counts are participant observations; use whole-game splits.",
    }
    _save(run_dir / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=BACKEND / "research_data" / "legacy-2025.jsonl.gz")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--judge-model", default="cohere/north-mini-code:free")
    parser.add_argument("--ignore-provider", action="append", default=[])
    parser.add_argument("--max-requests", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--include-invalid", action="store_true", help="Include defaulted/invalid games; their actions remain unscorable")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Persist the sample locally without any API or database calls")
    args = parser.parse_args(argv)
    if args.limit < 0 or args.max_requests < 1 or args.max_tokens < 1:
        parser.error("Limit must be nonnegative; request and token budgets must be positive")
    load_dotenv(BACKEND / ".env")
    run_dir, source = args.run_dir.resolve(), args.source.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    for folder in ("games", "judgments"):
        (run_dir / folder).mkdir(exist_ok=True)
    import fcntl
    with (run_dir / ".lock").open("w") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("This run directory already has an active worker")
        source_digest = _digest(source)
        manifest_path = run_dir / "manifest.json"
        settings = {key: getattr(args, key) for key in ("limit", "seed", "judge_model", "ignore_provider", "include_invalid", "max_tokens")}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest["source_export_sha256"] != source_digest or manifest["settings"] != settings:
                raise ValueError("Source or sample settings changed; use a new run directory")
        else:
            sampled = sample_legacy_games(read_export(source), limit=args.limit, seed=args.seed, include_invalid=args.include_invalid)
            manifest = {
                "schema_version": 1, "run_id": str(uuid.uuid4()), "kind": "legacy_public_commitment_labels",
                "created_at": time.time(), "source_export": str(source), "source_export_sha256": source_digest,
                "settings": settings, "selection": [{"game_id": game["game_id"], "source_match_id": game["source_match_id"], "models": game["models"]} for game in sampled["games"]],
                **{key: value for key, value in sampled.items() if key != "games"},
                "status": "prepared",
                "source_hashes": {name: _digest(BACKEND / "research" / name) for name in ("legacy.py", "judge.py", "openrouter.py", "database.py")},
            }
            for game in sampled["games"]:
                _save(run_dir / "games" / f"{game['game_id']}.json", game)
            _save(manifest_path, manifest)
        if args.prepare_only:
            print(json.dumps(summarize_legacy(run_dir, manifest)), flush=True)
            return
        catalog, key = fetch_metadata(os.environ["OPENROUTER_API_KEY"])
        judges = [model for model in catalog if isinstance(model, dict) and model.get("id") == args.judge_model and free_route(model)]
        if not judges:
            raise ValueError("Requested judge is not a currently validated free text route")
        _save(run_dir / "judge-catalog.json", {"models": judges, "safe_key_metadata": key, "checked_at": time.time()})
        remaining = (key.get("free_model_daily_requests") or {}).get("remaining")
        budget = min(args.max_requests, remaining) if isinstance(remaining, int) else args.max_requests
        client = FreeClient(os.environ["OPENROUTER_API_KEY"], judges, run_dir / "requests.jsonl",
                            max_requests=budget, ignored_providers=args.ignore_provider)
        store = None
        db_errors = []
        def sync(kind, payload, game_id=None):
            if store is not None:
                try:
                    if kind == "run":
                        store.put_run(manifest["run_id"], payload)
                    else:
                        getattr(store, "put_" + kind)(manifest["run_id"], game_id, payload)
                except Exception as exc:
                    db_errors.append({"kind": kind, "game_id": game_id, "error_type": type(exc).__name__})
        if not args.no_db:
            try:
                store = ResearchStore()
            except Exception as exc:
                db_errors.append({"kind": "connect", "error_type": type(exc).__name__})
        stop_reason = None
        manifest["status"] = "running"
        _save(manifest_path, manifest)
        sync("run", manifest)
        try:
            for entry in manifest["selection"]:
                game_id = entry["game_id"]
                game = json.loads((run_dir / "games" / f"{game_id}.json").read_text())
                sync("game", game, game_id)
                judgment_path = run_dir / "judgments" / f"{game_id}.json"
                if judgment_path.exists():
                    sync("judgment", json.loads(judgment_path.read_text()), game_id)
                    continue
                exhausted = []
                def completion(messages):
                    try:
                        response = client.complete(args.judge_model, messages, temperature=0, max_tokens=args.max_tokens,
                                                   context={"kind": "legacy_judge", "game_id": game_id, "source_match_id": game["source_match_id"]})
                        return response["choices"][0]["message"].get("content") or ""
                    except RequestBudgetExhausted as exc:
                        exhausted.append(exc)
                        raise
                judgment = judge_game(game, completion)
                if exhausted:
                    raise exhausted[0]
                judgment.update(game_id=game_id, source_match_id=game["source_match_id"], models=game["models"],
                                judge_model=args.judge_model, created_at=time.time())
                _save(judgment_path, judgment)
                sync("judgment", judgment, game_id)
                print(json.dumps({"game_id": game_id, "judge_status": judgment["judge_status"], "coverage": judgment["coverage"]}), flush=True)
        except (RequestBudgetExhausted, KeyboardInterrupt) as exc:
            stop_reason = str(exc) or "interrupted"
        finally:
            summary = summarize_legacy(run_dir, manifest)
            manifest.update(status="complete" if summary["judged_games"] == summary["selected_games"] else "partial",
                            stop_reason=stop_reason, last_invocation_requests=client.calls, reported_cost_usd=client.cost,
                            db_errors=db_errors, updated_at=time.time())
            _save(manifest_path, manifest)
            sync("run", manifest)
            if store is not None:
                store.close()
            print(json.dumps({**summary, "db_errors": db_errors}), flush=True)


if __name__ == "__main__":
    main()
