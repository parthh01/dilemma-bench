#!/usr/bin/env python3
"""
Reconstruct agent ratings using a simplified Glicko system with Rating Deviation (RD).

Assumptions and simplifications:
- No inactivity/temporal RD increase. RD only decreases as matches are played.
- Process all matches strictly in chronological order by `created_at`.
- Use standard Glicko-1 update per match (single opponent per rating period):
  - r: rating (centered at 1500)
  - RD: rating deviation; initial RD=350, floored at 30
  - q = ln(10) / 400
  - g(RD) = 1 / sqrt(1 + 3*q^2*RD^2/pi^2)
  - E(r, r_j, RD_j) = 1 / (1 + 10^(-g(RD_j) * (r - r_j)/400))
  - v = 1 / (q^2 * g(RD_j)^2 * E * (1 - E))
  - r' = r + (q / (1/RD^2 + 1/v)) * g(RD_j) * (s - E)
  - RD' = sqrt(1 / (1/RD^2 + 1/v))

Output:
- A CSV file containing final ratings for all agents: agent_id, agent_name, matches_played, rating, rd

Usage:
  python backend/recompute_glicko.py --output backend/glicko_ratings.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from typing import Dict, Tuple
from dotenv import load_dotenv
load_dotenv('.env')
import os
import sys

# Ensure this script can import sibling modules under backend/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from db.definition import Session, engine, Matches, Agents


# Glicko constants and defaults
DEFAULT_RATING: float = 1500.0
DEFAULT_RD: float = 350.0
MIN_RD: float = 30.0  # Floor to prevent RD collapsing to 0
Q: float = math.log(10) / 400.0


@dataclass
class Rating:
    rating: float = DEFAULT_RATING
    rd: float = DEFAULT_RD
    matches_played: int = 0


def g_factor(opponent_rd: float) -> float:
    return 1.0 / math.sqrt(1.0 + (3.0 * (Q ** 2) * (opponent_rd ** 2)) / (math.pi ** 2))


def expected_score(player_rating: float, opponent_rating: float, opponent_rd: float) -> float:
    g = g_factor(opponent_rd)
    return 1.0 / (1.0 + 10.0 ** (-g * (player_rating - opponent_rating) / 400.0))


def update_glicko(player: Rating, opponent: Rating, score: float) -> Rating:
    """Return updated Rating for player after a single match vs opponent.

    score: 1.0 win, 0.5 draw, 0.0 loss
    """
    # Use pre-match values
    r, RD = player.rating, player.rd
    r_j, RD_j = opponent.rating, opponent.rd

    g = g_factor(RD_j)
    E = 1.0 / (1.0 + 10.0 ** (-g * (r - r_j) / 400.0))

    # v and delta per Glicko-1; single-opponent period
    v = 1.0 / (Q ** 2 * (g ** 2) * E * (1.0 - E) + 1e-12)  # numerical guard
    denom = (1.0 / (RD ** 2)) + (1.0 / v)
    m = Q / denom

    new_rating = r + m * g * (score - E)
    new_rd = math.sqrt(1.0 / denom)

    # Apply RD floor and increment matches
    new_rd = max(new_rd, MIN_RD)

    return Rating(rating=new_rating, rd=new_rd, matches_played=player.matches_played + 1)


def result_to_scores(result: int) -> Tuple[float, float]:
    """Convert stored match result to (s1, s2). 1: agent1 win, 2: agent2 win, 0: draw."""
    if result == 1:
        return 1.0, 0.0
    if result == 2:
        return 0.0, 1.0
    return 0.5, 0.5


def fetch_agents_map(session: Session) -> Dict[str, Tuple[str, str]]:
    """Return mapping agent_id(str) -> (agent_id_str, name)."""
    agents = session.query(Agents.id, Agents.name).all()
    out: Dict[str, Tuple[str, str]] = {}
    for a_id, name in agents:
        out[str(a_id)] = (str(a_id), name)
    return out


def reconstruct_glicko_ratings() -> Dict[str, Rating]:
    """Recompute Glicko ratings for all agents through chronological matches."""
    with Session(engine, expire_on_commit=False) as session:
        # Ordered by earliest first
        matches = (
            session.query(Matches)
            .order_by(Matches.created_at.asc())
            .all()
        )

        agents_info = fetch_agents_map(session)

    # Ratings are kept outside of session context; we do not write to DB
    ratings: Dict[str, Rating] = {agent_id: Rating() for agent_id in agents_info.keys()}

    for m in matches:
        a1_id = str(m.agent1_id)
        a2_id = str(m.agent2_id)

        # Ensure both present (in case DB contains entities not in agents table)
        if a1_id not in ratings:
            ratings[a1_id] = Rating()
        if a2_id not in ratings:
            ratings[a2_id] = Rating()

        r1_before = ratings[a1_id]
        r2_before = ratings[a2_id]

        s1, s2 = result_to_scores(m.result)

        # Compute updates using pre-match values for both sides
        r1_after = update_glicko(r1_before, r2_before, s1)
        r2_after = update_glicko(r2_before, r1_before, s2)

        ratings[a1_id] = r1_after
        ratings[a2_id] = r2_after

    return ratings


def write_csv(ratings: Dict[str, Rating], output_path: str) -> None:
    # Fetch names again for reporting without DB writes
    with Session(engine, expire_on_commit=False) as session:
        names_map = {str(a.id): a.name for a in session.query(Agents.id, Agents.name).all()}

    fieldnames = ["agent_id", "agent_name", "matches_played", "rating", "rd"]
    with open(output_path, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        #sort ratings by rating
        sorted_ratings = sorted(ratings.items(), key=lambda x: x[1].rating, reverse=True)
        for agent_id, rating in sorted_ratings:
            writer.writerow(
                {
                    "agent_id": agent_id,
                    "agent_name": names_map.get(agent_id, "Unknown Agent"),
                    "matches_played": rating.matches_played,
                    "rating": round(rating.rating, 2),
                    "rd": round(rating.rd, 2),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute Glicko ratings (no DB writes)")
    parser.add_argument(
        "--output",
        default="glicko_ratings.csv",
        help="Path to output CSV file",
    )
    args = parser.parse_args()

    ratings = reconstruct_glicko_ratings()
    write_csv(ratings, args.output)
    print(f"Wrote Glicko ratings to {args.output}")


if __name__ == "__main__":

    main()


