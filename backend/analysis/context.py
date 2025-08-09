from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from db.definition import engine, Agents, Matches, Transcripts, Users  # type: ignore


@dataclass
class AnalysisContext:
    """Shared context passed to plot functions.

    Provides an SQLAlchemy session via a context manager and exposes ORM models.
    """

    def session(self) -> Session:
        return Session(bind=engine, expire_on_commit=False)

    @property
    def Models(self):
        class _M:
            Agents_ = Agents
            Matches_ = Matches
            Transcripts_ = Transcripts
            Users_ = Users

        return _M


