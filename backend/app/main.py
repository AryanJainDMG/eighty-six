"""The API.

Five endpoints. The interesting one is /ask, and the interesting thing
about it is the order of operations: the dossier is built, the model is
called, and then the reply is checked *before it is returned*. A leak that
reaches the page is a leak the player can read, so the detector has to run
on this side of the wire.

The detector's findings are returned alongside the answer rather than used
to suppress it. That is a deliberate difference from a production system,
where you would withhold the reply: here the leak is the thing worth
seeing, so the page shows it underlined in red.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .case import briefing
from .leak import as_dicts, detect
from .llm import get_provider
from .session import Turn, store
from .suspects import account_of, build_dossier
from .world import clock

app = FastAPI(title="Eighty-Six", version="1.0")

# The frontend is served from a different origin (a static host), so the
# browser needs permission to call this. Locked to configured origins rather
# than "*" — this is a public endpoint that spends someone's API quota, and
# leaving it open to any page on the internet is how that quota disappears.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "EIGHTYSIX_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

provider = get_provider()

MAX_QUESTION_CHARS = 500


class NewGame(BaseModel):
    seed: int | None = None
    mode: str = Field(default="need_to_know", pattern="^(need_to_know|naive)$")


class Question(BaseModel):
    session_id: str
    suspect_id: str
    question: str


class Accusation(BaseModel):
    session_id: str
    suspect_id: str


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "provider": provider.name}


@app.post("/api/new")
def new_game(body: NewGame) -> dict:
    session = store.new(seed=body.seed, mode=body.mode)
    return {
        "session_id": session.id,
        "seed": session.case.seed,
        "mode": session.mode,
        "provider": provider.name,
        **briefing(session.case),
    }


@app.post("/api/ask")
def ask(body: Question) -> dict:
    session = store.get(body.session_id)
    if not session:
        raise HTTPException(404, "No such investigation — start a new one.")
    if body.suspect_id not in session.case.people:
        raise HTTPException(404, "No such suspect.")

    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Ask them something.")
    # A cap, because the question goes straight into someone else's prompt
    # and an unbounded field on a public endpoint is an unbounded bill.
    question = question[:MAX_QUESTION_CHARS]

    dossier = build_dossier(session.case, body.suspect_id, session.mode)
    history = session.history_for(body.suspect_id)

    started = time.time()
    try:
        answer = provider.complete(dossier, history, question)
    except Exception as exc:  # noqa: BLE001 — surface any provider failure as 502
        raise HTTPException(502, f"The model did not answer: {exc}") from exc
    elapsed_ms = int((time.time() - started) * 1000)

    leaks = detect(session.case, body.suspect_id, answer)
    session.record(body.suspect_id, question, answer)
    session.turns.append(
        Turn(
            speaker=body.suspect_id,
            question=question,
            answer=answer,
            leaks=as_dicts(leaks),
            mode=session.mode,
            ms=elapsed_ms,
        )
    )

    return {
        "suspect_id": body.suspect_id,
        "answer": answer,
        "leaks": as_dicts(leaks),
        "ms": elapsed_ms,
        "mode": session.mode,
        "leak_count": len(session.turns and [t for t in session.turns if t.leaks]),
        "turn_count": len(session.turns),
    }


@app.post("/api/accuse")
def accuse(body: Accusation) -> dict:
    session = store.get(body.session_id)
    if not session:
        raise HTTPException(404, "No such investigation — start a new one.")

    case = session.case
    correct = body.suspect_id == case.culprit_id
    session.solved = correct

    leaked_turns = [t for t in session.turns if t.leaks]

    return {
        "correct": correct,
        "culprit": case.name(case.culprit_id),
        "culprit_id": case.culprit_id,
        "explanation": (
            f"{case.name(case.culprit_id)} was at the pass from "
            f"{clock(case.tamper_start)} to {clock(case.tamper_end)}, alone. "
            f"They said they were {case.place_name(case.alibi_place_id)} — but "
            f"{case.name(case.contradicting_witness_id)} was in "
            f"{case.place_name(case.alibi_place_id)} for that whole window and "
            "was on their own."
        ),
        "truth": {
            pid: account_of(case, pid) for pid in case.people
        },
        "stats": {
            "questions": len(session.turns),
            "turns_with_a_leak": len(leaked_turns),
            "mode": session.mode,
        },
    }


@app.get("/api/solution/{session_id}")
def solution(session_id: str) -> dict:
    """Give up. Used by the page's 'show me' button, and by nobody proud."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(404, "No such investigation.")
    return accuse(Accusation(session_id=session_id, suspect_id=session.case.culprit_id))
