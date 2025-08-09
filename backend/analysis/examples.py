from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt
import seaborn as sns

from .context import AnalysisContext
from .registry import register_plot


@register_plot
def elo_histogram(ctx: AnalysisContext) -> plt.Figure:
    """Histogram of agent ELOs."""
    with ctx.session() as session:
        Agents = ctx.Models.Agents_
        elos = [a.elo for a in session.query(Agents).all()]

    fig, ax = plt.subplots(figsize=(6, 4))
    sns.histplot(elos, bins=20, kde=True, ax=ax)
    ax.set_title("Agent ELO distribution")
    ax.set_xlabel("ELO")
    ax.set_ylabel("Count")
    return fig


@register_plot
def action_distribution(ctx: AnalysisContext) -> plt.Figure:
    """Bar chart of global action counts across all matches."""
    with ctx.session() as session:
        Matches = ctx.Models.Matches_
        all_matches = session.query(Matches).all()

    withhold = 0
    submit = 0
    for m in all_matches:
        if m.agent1_action == "withhold":
            withhold += 1
        elif m.agent1_action == "submit_evidence":
            submit += 1
        if m.agent2_action == "withhold":
            withhold += 1
        elif m.agent2_action == "submit_evidence":
            submit += 1

    fig, ax = plt.subplots(figsize=(5, 4))
    sns.barplot(x=["withhold", "submit_evidence"], y=[withhold, submit], ax=ax)
    ax.set_ylabel("Count")
    ax.set_title("Global action counts")
    return fig


@register_plot
def results_by_pair(ctx: AnalysisContext) -> plt.Figure:
    """Breakdown of match outcomes (wins/draws) overall."""
    with ctx.session() as session:
        Matches = ctx.Models.Matches_
        all_matches = session.query(Matches).all()

    wins_a1 = sum(1 for m in all_matches if m.result == 1)
    wins_a2 = sum(1 for m in all_matches if m.result == 2)
    draws = sum(1 for m in all_matches if m.result == 0)

    fig, ax = plt.subplots(figsize=(5, 4))
    sns.barplot(x=["agent1 win", "agent2 win", "draw"], y=[wins_a1, wins_a2, draws], ax=ax)
    ax.set_ylabel("Count")
    ax.set_title("Match results overall")
    return fig


