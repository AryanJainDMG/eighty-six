"""One investigation in progress.

State lives in a dictionary in memory. That is the right call for what this
is — a single-process demo with no login and nothing worth persisting — and
the wrong call for almost anything else, so the limitation is written down
rather than discovered:

- A restart loses every game in progress. On free hosting the service also
  sleeps after fifteen minutes of inactivity, so that happens routinely.
- Two instances would not share sessions, so this cannot be scaled
  horizontally as written.
- Nothing is ever evicted except by the cap below, so a busy day is a slow
  memory leak.

The fix for all three is the same — put sessions in Redis or Postgres,
keyed by the same id — and it is deliberately not done here, because it
would add a service to deploy and a credential to manage for a game whose
whole appeal is that you can open it and play.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .case import generate_case
from .world import Case

MAX_SESSIONS = 200
SESSION_TTL_SECONDS = 60 * 60 * 3


@dataclass
class Turn:
    speaker: str        # suspect id
    question: str
    answer: str
    leaks: list[dict]
    mode: str
    ms: int


@dataclass
class Session:
    id: str
    case: Case
    mode: str = "need_to_know"
    created: float = field(default_factory=time.time)
    transcript: dict[str, list[dict]] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    solved: bool | None = None

    def history_for(self, suspect_id: str) -> list[dict]:
        """What this suspect has already said, so they stay consistent.

        Per-suspect rather than global: a character who can see what another
        character said in a different room knows something they should not,
        which would be the project leaking through its own plumbing.
        """
        return self.transcript.setdefault(suspect_id, [])

    def record(self, suspect_id: str, question: str, answer: str) -> None:
        history = self.history_for(suspect_id)
        history.append({"role": "user", "text": question})
        history.append({"role": "model", "text": answer})
        # Keep the last few exchanges. Long histories cost tokens and, more
        # importantly, give a character more of its own earlier words to
        # contradict.
        del history[:-12]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def new(self, seed: int | None = None, mode: str = "need_to_know") -> Session:
        self._evict()
        seed = seed if seed is not None else int(uuid.uuid4().int % 100_000)
        session = Session(id=uuid.uuid4().hex[:12], case=generate_case(seed), mode=mode)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session and time.time() - session.created > SESSION_TTL_SECONDS:
            self._sessions.pop(session_id, None)
            return None
        return session

    def _evict(self) -> None:
        now = time.time()
        stale = [
            sid for sid, s in self._sessions.items()
            if now - s.created > SESSION_TTL_SECONDS
        ]
        for sid in stale:
            self._sessions.pop(sid, None)

        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.created)
            self._sessions.pop(oldest.id, None)


store = SessionStore()
