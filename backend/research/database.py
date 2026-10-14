"""Preserve historical games and store new research in separate tables.

This module deliberately does not import the web application or its SQLAlchemy
models: importing or starting those paths can create tables. Historical exports
are read-only; only constructing ResearchStore enables writes, limited to its
three new tables. No user records are queried. Connection values are never
included in export metadata.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import psycopg2
from psycopg2.extras import Json
from dotenv import dotenv_values


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
LEGACY_TABLES = ("agents", "matches", "transcripts")
MISSING_PROVENANCE = [
    "model_weight_revision",
    "tokenizer_revision_and_chat_template",
    "exact_rendered_model_inputs_and_token_ids",
    "decoding_parameters_and_random_seeds",
    "provider_routing_and_inference_runtime",
    "logits_and_token_log_probabilities",
    "residual_stream_activations",
    "J_lens_scores_and_analysis_configuration",
    "promise_labels_and_prediction_cutoffs",
]


class ResearchDatabaseError(RuntimeError):
    """A database error safe to print without connection values or payloads."""


def _connect_database(
    env_file: str | Path | None = None,
    *,
    readonly: bool,
    environment: Mapping[str, str] | None = None,
    connect_timeout: int = 10,
    statement_timeout_ms: int = 15000,
):
    """Connect with TLS and explicit transaction settings.

The existing Azure endpoint rejects libpq startup ``options`` containing
``default_transaction_read_only``. Set transaction attributes after connecting
and set the timeout inside that transaction instead. Environment variables
override the optional dotenv file without changing the process environment.
"""
    if connect_timeout < 1 or statement_timeout_ms < 1:
        raise ValueError("Connection and statement timeouts must be positive")
    configuration = dict(dotenv_values(env_file or BACKEND_DIRECTORY / ".env"))
    configuration.update(os.environ if environment is None else environment)
    required = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [key for key in required if not configuration.get(key)]
    if missing:
        raise ValueError("Missing database configuration: " + ", ".join(missing))
    connection = None
    try:
        connection = psycopg2.connect(
            host=configuration["POSTGRES_HOST"],
            port=configuration.get("POSTGRES_PORT") or "5432",
            user=configuration["POSTGRES_USER"],
            password=configuration["POSTGRES_PASSWORD"],
            dbname=configuration["POSTGRES_DB"],
            sslmode="require",
            connect_timeout=connect_timeout,
        )
        connection.set_session(
            readonly=readonly,
            isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED",
            autocommit=False,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", (statement_timeout_ms,))
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != ("on" if readonly else "off"):
                raise RuntimeError("Database transaction settings were not applied")
        return connection
    except Exception as error:
        if connection is not None:
            connection.close()
        # Driver messages can include connection identifiers. Keep errors safe
        # to display in logs while preserving the error class for diagnosis.
        raise ResearchDatabaseError(
            f"PostgreSQL connection failed ({type(error).__name__})"
        ) from None


def connect_readonly_database(
    env_file: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    connect_timeout: int = 10,
    statement_timeout_ms: int = 15000,
):
    """Connect with TLS and a repeatable-read, read-only transaction."""
    return _connect_database(
        env_file,
        readonly=True,
        environment=environment,
        connect_timeout=connect_timeout,
        statement_timeout_ms=statement_timeout_ms,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ResearchStore:
    """Store new experiment data in three additive, purpose-specific tables.

    Constructing this class creates only ``dilemma_research_*`` tables if they
    are absent. It never reads or changes historical tables. Writes are upserts
    keyed by run and game IDs, so retrying a completed operation is idempotent.
    """

    def __init__(
        self,
        env_file: str | Path | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        statement_timeout_ms: int = 15000,
    ):
        self.statement_timeout_ms = statement_timeout_ms
        self.connection = _connect_database(
            env_file,
            readonly=False,
            environment=environment,
            statement_timeout_ms=statement_timeout_ms,
        )
        try:
            with self.connection:
                with self.connection.cursor() as cursor:
                    self._timeouts(cursor)
                    cursor.execute(
                        """CREATE TABLE IF NOT EXISTS public.dilemma_research_runs (
                            run_id TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )"""
                    )
                    cursor.execute(
                        """CREATE TABLE IF NOT EXISTS public.dilemma_research_games (
                            run_id TEXT NOT NULL,
                            game_id TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            PRIMARY KEY (run_id, game_id)
                        )"""
                    )
                    cursor.execute(
                        """CREATE TABLE IF NOT EXISTS public.dilemma_research_judgments (
                            run_id TEXT NOT NULL,
                            game_id TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            PRIMARY KEY (run_id, game_id)
                        )"""
                    )
        except Exception as error:
            self.connection.close()
            raise ResearchDatabaseError(
                f"Research table initialization failed ({type(error).__name__})"
            ) from None

    def _timeouts(self, cursor) -> None:
        cursor.execute("SET LOCAL statement_timeout = %s", (self.statement_timeout_ms,))
        cursor.execute("SET LOCAL lock_timeout = '2000ms'")

    @staticmethod
    def _payload(payload: Mapping[str, Any]) -> Json:
        return Json(payload, dumps=lambda value: json.dumps(value, default=_json_default))

    def _write(self, query: str, parameters: tuple) -> None:
        try:
            with self.connection:
                with self.connection.cursor() as cursor:
                    self._timeouts(cursor)
                    cursor.execute(query, parameters)
        except Exception as error:
            raise ResearchDatabaseError(
                f"Research data write failed ({type(error).__name__})"
            ) from None

    def put_run(self, run_id: str, payload: Mapping[str, Any]) -> None:
        self._write(
            """INSERT INTO public.dilemma_research_runs (run_id, payload)
               VALUES (%s, %s)
               ON CONFLICT (run_id) DO UPDATE
               SET payload=EXCLUDED.payload, updated_at=now()""",
            (run_id, self._payload(payload)),
        )

    def put_game(self, run_id: str, game_id: str, payload: Mapping[str, Any]) -> None:
        self._write(
            """INSERT INTO public.dilemma_research_games (run_id, game_id, payload)
               VALUES (%s, %s, %s)
               ON CONFLICT (run_id, game_id) DO UPDATE
               SET payload=EXCLUDED.payload, updated_at=now()""",
            (run_id, game_id, self._payload(payload)),
        )

    def put_judgment(self, run_id: str, game_id: str, payload: Mapping[str, Any]) -> None:
        self._write(
            """INSERT INTO public.dilemma_research_judgments (run_id, game_id, payload)
               VALUES (%s, %s, %s)
               ON CONFLICT (run_id, game_id) DO UPDATE
               SET payload=EXCLUDED.payload, updated_at=now()""",
            (run_id, game_id, self._payload(payload)),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _dict_rows(cursor):
    names = [column.name for column in cursor.description]
    for row in cursor:
        yield dict(zip(names, row))


def export_legacy_games(
    destination: str | Path,
    *,
    summary_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    """Export matches with model names and ordered transcripts, never users.

The gzip JSONL contains one complete match per line. All historical match and
transcript columns are retained; agent records contain only their ID and model
name. Existing output files are not overwritten.
"""
    destination = Path(destination).resolve()
    summary_path = (
        Path(summary_path).resolve()
        if summary_path is not None
        else destination.with_name("legacy-summary.json")
    )
    if destination.exists() or summary_path.exists():
        raise FileExistsError("An export or summary already exists; choose new paths")
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_readonly_database(env_file)
    temporary_path = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            server_version = cursor.fetchone()[0]
            cursor.execute(
                """SELECT table_name, column_name, data_type, is_nullable
                   FROM information_schema.columns
                   WHERE table_schema='public' AND table_name = ANY(%s)
                   ORDER BY table_name, ordinal_position""",
                (list(LEGACY_TABLES),),
            )
            schema = list(_dict_rows(cursor))
            cursor.execute("SELECT id, name FROM public.agents ORDER BY id")
            agents = {str(row["id"]): row for row in _dict_rows(cursor)}
            cursor.execute(
                """SELECT id, agent1_id, agent2_id, agent1_action, agent2_action,
                          agent1_default, agent2_default, result, created_at
                   FROM public.matches ORDER BY id"""
            )
            matches = {str(row["id"]): row for row in _dict_rows(cursor)}

        action_pairs: Counter = Counter()
        default_combinations: Counter = Counter()
        speaker_counts: Counter = Counter()
        transcript_total = 0
        nonempty_messages = 0
        matches_with_transcripts = 0
        matches_with_both_speakers = 0
        exported_matches = set()

        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".legacy-export-", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as zipped:
                with io.TextIOWrapper(zipped, encoding="utf-8") as output:

                    def emit(match_id: str, transcripts: list[dict[str, Any]]):
                        nonlocal matches_with_transcripts, matches_with_both_speakers
                        match = matches[match_id]
                        record = {
                            "record_type": "legacy_match",
                            "schema_version": 1,
                            "match": match,
                            "agents": {
                                "agent1": agents[str(match["agent1_id"])],
                                "agent2": agents[str(match["agent2_id"])],
                            },
                            "transcripts": transcripts,
                            "provenance": {
                                "source": "legacy_database",
                                "historical_api_game": True,
                                "missing": MISSING_PROVENANCE,
                            },
                        }
                        output.write(json.dumps(record, default=_json_default, ensure_ascii=False))
                        output.write("\n")
                        exported_matches.add(match_id)
                        action_pairs[(match["agent1_action"], match["agent2_action"])] += 1
                        default_combinations[(match["agent1_default"], match["agent2_default"])] += 1
                        if transcripts:
                            matches_with_transcripts += 1
                        nonempty_speakers = {row["agent_id"] for row in transcripts if row["message"]}
                        if {1, 2} <= nonempty_speakers:
                            matches_with_both_speakers += 1

                    with connection.cursor(name="legacy_game_export") as cursor:
                        cursor.itersize = 500
                        cursor.execute(
                            """SELECT id, match_id, message, agent_id, \"order\", created_at
                               FROM public.transcripts
                               ORDER BY match_id, \"order\", created_at, id"""
                        )
                        current_match_id = None
                        transcripts: list[dict[str, Any]] = []
                        # A named cursor's description is populated after the
                        # first fetch; the explicit query fixes this field order.
                        fields = ("id", "match_id", "message", "agent_id", "order", "created_at")
                        for values in cursor:
                            row = dict(zip(fields, values))
                            match_id = str(row["match_id"])
                            if match_id not in matches:
                                raise ValueError("Historical database has an orphan transcript")
                            if current_match_id is not None and match_id != current_match_id:
                                emit(current_match_id, transcripts)
                                transcripts = []
                            current_match_id = match_id
                            transcripts.append(row)
                            transcript_total += 1
                            speaker_counts[row["agent_id"]] += 1
                            nonempty_messages += bool(row["message"])
                        if current_match_id is not None:
                            emit(current_match_id, transcripts)
                    for match_id in matches:
                        if match_id not in exported_matches:
                            emit(match_id, [])

        # Read the compressed export back before publishing it. This validates
        # decompression, JSON encoding, unique matches, and transcript counts.
        verified_ids = set()
        verified_transcript_count = 0
        with gzip.open(temporary_path, "rt", encoding="utf-8") as exported:
            for line in exported:
                record = json.loads(line)
                match_id = record["match"]["id"]
                if match_id in verified_ids:
                    raise ValueError("Duplicate match in historical export")
                verified_ids.add(match_id)
                verified_transcript_count += len(record["transcripts"])
        if verified_ids != set(matches) or verified_transcript_count != transcript_total:
            raise ValueError("Historical export verification failed")

        digest = hashlib.sha256()
        with temporary_path.open("rb") as exported:
            for chunk in iter(lambda: exported.read(1024 * 1024), b""):
                digest.update(chunk)
        dates = [row["created_at"] for row in matches.values() if row["created_at"]]
        summary = {
            "schema_version": 1,
            "export_created_at": datetime.now(timezone.utc).isoformat(),
            "source": "legacy_database",
            "database_version": server_version,
            "database_read_only": True,
            "snapshot_isolation": "repeatable read",
            "tls_in_use": connection.info.ssl_in_use,
            "tables_exported": list(LEGACY_TABLES),
            "agent_fields_exported": ["id", "name"],
            "database_schema": schema,
            "export_file": destination.name,
            "export_sha256": digest.hexdigest(),
            "compressed_bytes": temporary_path.stat().st_size,
            "agents": len(agents),
            "matches": len(matches),
            "transcripts": transcript_total,
            "nonempty_messages": nonempty_messages,
            "matches_with_transcripts": matches_with_transcripts,
            "matches_with_nonempty_messages_from_both_agents": matches_with_both_speakers,
            "match_date_range": [min(dates), max(dates)] if dates else [None, None],
            "action_pairs": [
                {"agent1_action": pair[0], "agent2_action": pair[1], "matches": count}
                for pair, count in sorted(action_pairs.items())
            ],
            "default_combinations": [
                {"agent1_default": pair[0], "agent2_default": pair[1], "matches": count}
                for pair, count in sorted(default_combinations.items())
            ],
            "transcript_speaker_counts": dict(sorted(speaker_counts.items())),
            "missing_provenance": MISSING_PROVENANCE,
            "limitations": [
                "Historical timestamps have no timezone; values are preserved without assuming UTC.",
                "Defaulted actions must be distinguished from intentionally selected actions.",
                "Text and final actions alone do not establish deceptive intent at an earlier promise.",
                "Historical closed-model activations cannot be recovered from this export.",
                "Rows from the users table are never queried or exported.",
            ],
            "verification": {
                "gzip_and_json_readback": "passed",
                "unique_match_ids": len(verified_ids),
                "transcripts_read_back": verified_transcript_count,
            },
        }
        temporary_path.replace(destination)
        temporary_path = None
        with summary_path.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2, default=_json_default, ensure_ascii=False)
            output.write("\n")
        return summary
    finally:
        connection.rollback()
        connection.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export historical model games without user records")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--env-file", type=Path)
    arguments = parser.parse_args()
    summary = export_legacy_games(
        arguments.output, summary_path=arguments.summary, env_file=arguments.env_file
    )
    print(json.dumps({key: summary[key] for key in (
        "export_file", "export_sha256", "compressed_bytes", "agents", "matches", "transcripts"
    )}, indent=2))


if __name__ == "__main__":
    main()
