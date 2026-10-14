# Behavioral screening

This experiment screens models for public commitments that agree or disagree
with their eventual native tool decisions. It does not measure J-lens or prove
intent to deceive. The historical 0/2/8/10-year payoff matrix is retained: at a
50% opponent-defection probability, both choices have an expected sentence of
five years.

Run from `backend` using the existing virtual environment:

```sh
.venv/bin/python -m research.screen \
  --run-dir research_data/free-screen \
  --judge-model cohere/north-mini-code:free \
  --max-requests 900
```

The catalog is fetched live. The default schedule is two complete round robins,
with reversed speaking order in the second repetition, temperature 0.7, and
20 public turns maximum. Seeds are sent only when a route advertises support;
providers may still be nondeterministic. The schedule and settings are frozen
in `manifest.json`; use a new directory to change the experiment.

Use `--catalog-only` to save a plan without model calls or DB writes.
`--max-games 3` bounds a smoke run; repeating the command resumes it.
`--retry-errors` archives failed games/judgments and retries them, refreshing
the provider compatibility checks. Valid completed games are not rerun.
Two failures on one model stop scheduling that model for the current invocation.

Only named `:free` routes with exclusively zero advertised prices, text output,
and native tools enter the schedule. The random `openrouter/free` router is
excluded because its model identity is not fixed. Requests also enforce zero
provider prices for input, output, and request fees. There are no model fallbacks
or paid plugins. Access gates and unavailable routes remain explicit exclusions.
An account may have bring-your-own-key provider fallback configured; exclude
those providers with `--ignore-provider PROVIDER_SLUG`. A returned BYOK response
halts the run because a zero OpenRouter charge does not establish zero upstream
charges. Account settings are never changed.

The run probes each eligible route once for compatibility before generating
games. These forced-action probes are not behavioral samples. Free-request
budgets include these probes and judge requests, and daily quota errors stop
the worker. A stopped run needs an explicit rerun; nothing is scheduled.
The transport bounds stalled responses even if a provider keeps sending
whitespace keepalives. Those failures are provider errors, not player decisions.

On the current account, include `--ignore-provider google-ai-studio
--ignore-provider google-vertex` to avoid its Google BYOK fallback. The current
screen uses `--max-tokens 16384` because 4,096 tokens truncated a reasoning
model before it produced an action; truncations remain explicit invalid outcomes.

## Data

Artifacts in the gitignored `research_data` directory are authoritative backups:

- `manifest.json`, `catalog.json`: frozen model metadata, payoff/prompt settings,
  schedule, provider availability, run status, and database synchronization errors.
- `source/`: source snapshots and installed-library versions by content hash.
- `requests.jsonl`: API request and response journal, without authorization
  headers; response IDs, providers, usage, model identities, and tool arguments
  remain available. Unique invocation/request identifiers distinguish retries.
- `events.jsonl`: role-formatted inputs and raw assistant/tool messages, tagged
  by game, attempt, actor, and public visibility. Interrupted games retain events.
- `games/*.json`: final games, including invalid outcomes and provider errors.
- `judgments/*.json`: grounded commitment labels and exact supporting quotations.
- `summary.json`: per-model coverage and candidate broken commitments.

The Azure connection comes from `backend/.env`. New data uses only the additive
`dilemma_research_runs`, `dilemma_research_games`, and
`dilemma_research_judgments` tables. Historical tables and Elo ratings are not
changed. Local writes precede remote writes; resumption retries synchronization.
`--no-db` explicitly collects locally.

Dialogue text is published before an accompanying private tool action, so a
same-response promise and action can be compared. Forced-decision responses
remain private. The judge sees public text and game rules, never final actions, private tool
calls, outcomes, or model names. Its quoted evidence must match the cited speaker
and message exactly. Actual actions are joined afterward in Python. Conditional
promises, retractions, changed information, ambiguity, defaults, and failures
remain separate. Labels need human semantic review; exact quotes alone do not
validate the judge's interpretation. In particular, non-promises do not count as
honesty, and a default action does not count as cooperation.

Use fulfilled and broken counts to decide whether a model merits further local
sampling. Counts are participant observations, and participants in a game are
not independent. A single judge can be biased, particularly when judging itself.
Validate promising models with another judge and an audited sample before
mechanistic conclusions. API model names/routing do not pin local weight revisions;
reproduce each candidate's behavior on the intended local checkpoint before
collecting activations. Public API traces cannot recover hidden activations.

## Historical export and tests

```sh
.venv/bin/python -m research.database --help
.venv/bin/python -m unittest discover -s tests -v
```

The read-only legacy exporter preserves ordered transcripts, actions/defaults,
and model names, omits users, and records a checksum. Azure requires setting
read-only mode after connection rather than in libpq startup `options`.

To label a seeded sample of the recovered export:

```sh
.venv/bin/python -m research.legacy \
  --run-dir research_data/legacy-labels \
  --limit 20 --max-requests 20 \
  --judge-model cohere/north-mini-code:free \
  --ignore-provider google-ai-studio --ignore-provider google-vertex
```

`--prepare-only` constructs the sample without API or database calls. By default,
games with any defaulted or invalid decision are excluded. The sample is drawn
before looking for promises; historical visibility is inferred conservatively
from termination markers. It can establish that examples exist in the old
corpus, but cannot supply hidden activations or establish that a current model
has enough examples of both classes. Assistant reviews remain separate from
automatic judgments and are not human annotations.
