from __future__ import annotations

from typing import Dict, List, Tuple
from sqlalchemy import func

import matplotlib.pyplot as plt
import seaborn as sns

from .context import AnalysisContext
from .registry import register_plot


def _short_label(model_name: str) -> str:
    # Produce compact labels for report visuals
    if model_name.startswith("meta-llama/llama-3.1-") and model_name.endswith("-instruct"):
        core = model_name.split("llama-3.1-")[-1].replace("-instruct", "").upper()
        return core
    if model_name.startswith("meta-llama/llama-3.2-") and model_name.endswith("-instruct"):
        core = model_name.split("llama-3.2-")[-1].replace("-instruct", "").upper()
        return core
    if model_name.startswith("openai/gpt-"):
        core = model_name.split("openai/")[-1]
        core = core.replace("gpt-", "").replace("mini", "mini").replace("-", ".")
        # Normalize e.g., 4o names
        core = core.replace("4.o", "4o").replace(".o", "o")
        return core
    if model_name.startswith("mistralai/mistral-"):
        core = model_name.split("mistral-")[-1]
        core = core.replace("7b-instruct-v0.3", "7b").replace("large", "123b")
        return core
    if model_name.startswith("anthropic/claude-"):
        core = model_name.split("claude-")[-1]
        core = core.replace("sonnet-4", "S4").replace("opus-4", "O4")
        return core
    if model_name.startswith("google/gemini-"):
        core = model_name.split("gemini-")[-1]
        core = core.replace("2.5-flash", "Flash").replace("2.5-pro", "Pro")
        return core
    if model_name.startswith("x-ai/grok-"):
        core = model_name.split("grok-")[-1]
        core = core.replace("3-mini", "3m").replace("3", "3")
        return core
    return model_name


def _get_agent_by_name(ctx: AnalysisContext, model_name: str):
    with ctx.session() as session:
        Agents = ctx.Models.Agents_
        return session.query(Agents).filter(Agents.name == model_name).first()


def _get_agent_elo_and_actions(ctx: AnalysisContext, agent_id) -> Tuple[int | None, Dict[str, int]]:
    with ctx.session() as session:
        Agents = ctx.Models.Agents_
        Matches = ctx.Models.Matches_

        agent = session.query(Agents).filter(Agents.id == agent_id).first()
        if not agent:
            return None, {"withhold": 0, "submit_evidence": 0}

        all_matches = session.query(Matches).filter((Matches.agent1_id == agent.id) | (Matches.agent2_id == agent.id)).all()
        withhold = 0
        submit = 0
        for m in all_matches:
            is_agent1 = m.agent1_id == agent.id
            if is_agent1:
                if m.agent1_default:
                    continue  # do not count defaulted move
                action = m.agent1_action
            else:
                if m.agent2_default:
                    continue  # do not count defaulted move
                action = m.agent2_action

            if action == "withhold":
                withhold += 1
            elif action == "submit_evidence":
                submit += 1

        return agent.elo, {"withhold": withhold, "submit_evidence": submit}


@register_plot
def model_series_elo_and_actions(ctx: AnalysisContext) -> plt.Figure:
    """Compare ELO and action distribution across model size/variants for specified series.

    Produces a single figure with two charts:
    - Left: grouped (clustered) bar chart of ELO with one cluster per model series and a bar per variant
    - Right: grouped 100% stacked bars of action distribution (withhold vs submit_evidence) per variant within each series
    """
    sns.set_theme(style="whitegrid")

    series: Dict[str, List[str]] = {
        "Llama 3.1": [
            "meta-llama/llama-3.1-8b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "meta-llama/llama-3.1-405b-instruct",
        ],
        "GPT-5": [
            "openai/gpt-5-mini",
            "openai/gpt-5",
        ],
        "GPT-4.1": [
            "openai/gpt-4.1-mini",
            "openai/gpt-4.1",
        ],
        "GPT-4o": [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
        ],
        "Gemini 2.5": [
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
        ],
        "Mistral": [
            "mistralai/mistral-7b-instruct-v0.3",
            "mistralai/mistral-large"
        ],
        "Claude 4-": [
            "anthropic/claude-sonnet-4",
            "anthropic/claude-opus-4",
        ],
        "Grok-3": [
            "x-ai/grok-3-mini",
            "x-ai/grok-3",
        ]
    }

    sns.set_theme(style="whitegrid")
    series_names = list(series.keys())

    # Collect values
    elo_values: List[List[int | None]] = []
    action_withhold: List[List[float]] = []
    action_submit: List[List[float]] = []
    variant_labels: List[List[str]] = []
    missing_by_series: List[List[str]] = []

    for title in series_names:
        models = series[title]
        series_elos: List[int | None] = []
        series_withhold: List[float] = []
        series_submit: List[float] = []
        labels: List[str] = []
        missing: List[str] = []

        for model_name in models:
            agent = _get_agent_by_name(ctx, model_name)
            labels.append(_short_label(model_name))
            if not agent:
                series_elos.append(None)
                series_withhold.append(0.0)
                series_submit.append(0.0)
                missing.append(model_name)
                continue

            elo, counts = _get_agent_elo_and_actions(ctx, agent.id)
            total = counts["withhold"] + counts["submit_evidence"]
            series_elos.append(elo if elo is not None else None)
            if total > 0:
                series_submit.append(counts["submit_evidence"] / total)
                series_withhold.append(counts["withhold"] / total)
            else:
                series_submit.append(0.0)
                series_withhold.append(0.0)

        elo_values.append(series_elos)
        action_withhold.append(series_withhold)
        action_submit.append(series_submit)
        variant_labels.append(labels)
        missing_by_series.append(missing)

    # Layout: two subplots (ELO left, action right)
    fig, (ax_elo, ax_actions) = plt.subplots(nrows=1, ncols=2, figsize=(14, 5.5), gridspec_kw={"wspace": 0.35})

    # Clustered ELO bars
    max_variants = max(len(v) for v in elo_values)
    base_x = list(range(len(series_names)))
    bar_width = 0.18
    cluster_width = max_variants * bar_width + (max_variants - 1) * 0.04
    start_offset = -cluster_width / 2 + bar_width / 2

    colors = [sns.color_palette("colorblind")[0], sns.color_palette("colorblind")[1], sns.color_palette("colorblind")[2]]

    for s_idx, series_elos in enumerate(elo_values):
        n = len(series_elos)
        for v_idx, elo in enumerate(series_elos):
            x = base_x[s_idx] + start_offset + v_idx * (bar_width + 0.04)
            if elo is None:
                continue
            rect = ax_elo.bar(x, int(elo), width=bar_width, color=colors[v_idx % len(colors)], edgecolor="#333333", linewidth=0.5)
            # Labels: variant and value
            ax_elo.text(x, int(elo) + 6, f"{variant_labels[s_idx][v_idx]}", ha="center", va="bottom", fontsize=8, color="#444444")

    ax_elo.set_xticks(base_x)
    ax_elo.set_xticklabels(series_names, rotation=90, ha="center", va="top")
    ax_elo.set_ylabel("ELO", labelpad=10)
    ax_elo.set_title("ELO by model series (clustered by variant)", fontsize=12, pad=10)
    ax_elo.set_ylim(bottom=950)
    ax_elo.margins(y=0.2)
    ax_elo.tick_params(axis="x", pad=8)

    # Grouped 100% stacked action bars per variant
    action_colors = {"submit_evidence": sns.color_palette("colorblind")[2], "withhold": sns.color_palette("colorblind")[3]}
    for s_idx in range(len(series_names)):
        n = len(action_withhold[s_idx])
        for v_idx in range(n):
            x = base_x[s_idx] + start_offset + v_idx * (bar_width + 0.04)
            w = action_withhold[s_idx][v_idx]
            u = action_submit[s_idx][v_idx]
            ax_actions.bar(x, w, width=bar_width, color=action_colors["withhold"], edgecolor="#333333", linewidth=0.4)
            ax_actions.bar(x, u, bottom=w, width=bar_width, color=action_colors["submit_evidence"], edgecolor="#333333", linewidth=0.4)

    ax_actions.set_xticks(base_x)
    ax_actions.set_xticklabels(series_names, rotation=90, ha="center", va="top")
    ax_actions.set_ylim(0, 1)
    ax_actions.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax_actions.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax_actions.set_ylabel("Action distribution (share)", labelpad=10)
    ax_actions.set_title("Actions by model series (clustered by variant)", fontsize=12, pad=10)
    ax_actions.tick_params(axis="x", pad=8)

    # Missing note in suptitle if any
    missing_notes = []
    for name, missing in zip(series_names, missing_by_series):
        if missing:
            missing_notes.append(f"{name}: {len(missing)} missing")
    subtitle = "  |  ".join(missing_notes)
    if subtitle:
        fig.suptitle(f"Model series: ELO and action distributions\n{subtitle}", fontsize=16)
    else:
        fig.suptitle("Model series: ELO and action distributions", fontsize=16)

    fig.subplots_adjust(top=0.88, bottom=0.22, left=0.06, right=0.98)
    return fig


@register_plot
def agents_correlation_elo_vs_submit(ctx: AnalysisContext) -> plt.Figure:
    """Pearson correlation between ELO and submit_evidence share (%) for all agents.

    Excludes defaulted moves from action tallies.
    """
    sns.set_theme(style="whitegrid")

    # Pull all agents and all matches once
    with ctx.session() as session:
        Agents = ctx.Models.Agents_
        Matches = ctx.Models.Matches_
        agents = session.query(Agents.id, Agents.name, Agents.elo).all()
        matches = session.query(
            Matches.agent1_id,
            Matches.agent2_id,
            Matches.agent1_action,
            Matches.agent2_action,
            Matches.agent1_default,
            Matches.agent2_default,
        ).all()

    # Tally actions per agent (ignoring defaulted)
    submit_counts: dict[str, int] = {}
    withhold_counts: dict[str, int] = {}

    for m in matches:
        a1 = str(m.agent1_id)
        a2 = str(m.agent2_id)
        if not m.agent1_default:
            if m.agent1_action == "submit_evidence":
                submit_counts[a1] = submit_counts.get(a1, 0) + 1
            elif m.agent1_action == "withhold":
                withhold_counts[a1] = withhold_counts.get(a1, 0) + 1
        if not m.agent2_default:
            if m.agent2_action == "submit_evidence":
                submit_counts[a2] = submit_counts.get(a2, 0) + 1
            elif m.agent2_action == "withhold":
                withhold_counts[a2] = withhold_counts.get(a2, 0) + 1

    # Build vectors for correlation
    xs_submit_pct: list[float] = []
    ys_elo: list[float] = []
    for agent_id, _name, elo in agents:
        aid = str(agent_id)
        s = submit_counts.get(aid, 0)
        w = withhold_counts.get(aid, 0)
        total = s + w
        if total <= 0:
            continue
        xs_submit_pct.append((s / total) * 100.0)
        ys_elo.append(float(elo))

    # Compute Pearson r (no external dependency)
    def _pearson(x: list[float], y: list[float]) -> float | None:
        n = len(x)
        if n < 2:
            return None
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        den_x = (sum((xi - mean_x) ** 2 for xi in x)) ** 0.5
        den_y = (sum((yi - mean_y) ** 2 for yi in y)) ** 0.5
        if den_x == 0 or den_y == 0:
            return None
        return num / (den_x * den_y)

    r = _pearson(xs_submit_pct, ys_elo)

    fig, ax = plt.subplots(figsize=(8.5, 6.0))

    # Scatter points
    ax.scatter(xs_submit_pct, ys_elo, s=28, color=sns.color_palette("colorblind")[0], alpha=0.45, edgecolor="none")

    # Best-fit line (least squares)
    # if len(xs_submit_pct) >= 2:
    #     x_mean = sum(xs_submit_pct) / len(xs_submit_pct)
    #     y_mean = sum(ys_elo) / len(ys_elo)
    #     s_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs_submit_pct, ys_elo))
    #     s_xx = sum((x - x_mean) ** 2 for x in xs_submit_pct)
    #     if s_xx > 0:
    #         slope = s_xy / s_xx
    #         intercept = y_mean - slope * x_mean
    #         x_min, x_max = min(xs_submit_pct), max(xs_submit_pct)
    #         ax.plot([x_min, x_max], [slope * x_min + intercept, slope * x_max + intercept], color="#2f2f2f", linewidth=2.0, linestyle="--", alpha=0.9)

    # Annotate r
    r_text = f"Pearson r = {r:.3f}" if r is not None else "Pearson r = N/A"
    ax.text(0.02, 0.98, r_text, transform=ax.transAxes, ha="left", va="top", fontsize=11, bbox=dict(facecolor="white", edgecolor="#cccccc", boxstyle="round,pad=0.3"))

    ax.set_xlabel("Defect rate (%)", labelpad=10)
    ax.set_ylabel("ELO", labelpad=10)
    ax.set_title("Correlation: ELO vs defect rate", fontsize=13, pad=10)
    ax.set_xlim(-2, 102)
    ax.margins(y=0.15)
    ax.grid(True, axis="both", linestyle=":", linewidth=0.6, alpha=0.6)

    fig.subplots_adjust(top=0.9, bottom=0.12, left=0.12, right=0.98)
    return fig


@register_plot
def agents_avg_length_vs_elo(ctx: AnalysisContext) -> plt.Figure:
    """Scatter of ELO vs average game length (number of messages) per agent.

    For each agent, compute the average number of transcript messages across
    all matches they participated in, and plot against their ELO.
    """
    sns.set_theme(style="whitegrid")

    with ctx.session() as session:
        Agents = ctx.Models.Agents_
        Matches = ctx.Models.Matches_
        Transcripts = ctx.Models.Transcripts_

        agents = session.query(Agents.id, Agents.name, Agents.elo).all()

        # Map match_id -> message_count
        counts = (
            session.query(Transcripts.match_id, func.count(Transcripts.id))
            .group_by(Transcripts.match_id)
            .all()
        )
        match_to_len = {str(mid): int(c) for (mid, c) in counts}

        # Map agent_id -> list of match_ids
        mrows = session.query(Matches.id, Matches.agent1_id, Matches.agent2_id).all()
        agent_to_matches: Dict[str, List[str]] = {}
        for mid, a1, a2 in mrows:
            mid_s = str(mid)
            a1_s = str(a1)
            a2_s = str(a2)
            agent_to_matches.setdefault(a1_s, []).append(mid_s)
            agent_to_matches.setdefault(a2_s, []).append(mid_s)

    xs_avg_len: List[float] = []
    ys_elo: List[float] = []
    labels: List[str] = []

    for agent_id, name, elo in agents:
        aid = str(agent_id)
        mids = agent_to_matches.get(aid, [])
        if not mids:
            continue
        lengths = [match_to_len[m] for m in mids if m in match_to_len]
        if not lengths:
            continue
        avg_len = sum(lengths) / len(lengths)
        xs_avg_len.append(avg_len)
        ys_elo.append(float(elo))
        labels.append(name)

    # Pearson correlation
    def _pearson(x: List[float], y: List[float]) -> float | None:
        n = len(x)
        if n < 2:
            return None
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = (sum((xi - mx) ** 2 for xi in x)) ** 0.5
        dy = (sum((yi - my) ** 2 for yi in y)) ** 0.5
        if dx == 0 or dy == 0:
            return None
        return num / (dx * dy)

    r = _pearson(xs_avg_len, ys_elo)

    fig, ax = plt.subplots(figsize=(8.5, 6.0))
    ax.scatter(xs_avg_len, ys_elo, s=28, color=sns.color_palette("colorblind")[0], alpha=0.45, edgecolor="none")

    # Best-fit line
    # if len(xs_avg_len) >= 2:
        # mx = sum(xs_avg_len) / len(xs_avg_len)
        # my = sum(ys_elo) / len(ys_elo)
        # s_xy = sum((x - mx) * (y - my) for x, y in zip(xs_avg_len, ys_elo))
        # s_xx = sum((x - mx) ** 2 for x in xs_avg_len)
        # if s_xx > 0:
        #     slope = s_xy / s_xx
        #     intercept = my - slope * mx
        #     x_min, x_max = min(xs_avg_len), max(xs_avg_len)
        #     ax.plot([x_min, x_max], [slope * x_min + intercept, slope * x_max + intercept], color="#2f2f2f", linewidth=2.0, linestyle="--", alpha=0.9)

    r_text = f"Pearson r = {r:.3f}" if r is not None else "Pearson r = N/A"
    ax.text(0.02, 0.98, r_text, transform=ax.transAxes, ha="left", va="top", fontsize=11, bbox=dict(facecolor="white", edgecolor="#cccccc", boxstyle="round,pad=0.3"))

    ax.set_xlabel("Avg messages per match", labelpad=10)
    ax.set_ylabel("ELO", labelpad=10)
    ax.set_title("ELO vs average game length (messages)", fontsize=13, pad=10)
    ax.margins(x=0.05, y=0.15)
    ax.grid(True, axis="both", linestyle=":", linewidth=0.6, alpha=0.6)

    fig.subplots_adjust(top=0.9, bottom=0.12, left=0.12, right=0.98)
    return fig
