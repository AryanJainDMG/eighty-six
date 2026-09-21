"""Tests, organised around the claims the project makes rather than the modules.

The one that matters is `test_need_to_know_dossier_contains_no_secrets`. It
is the whole thesis expressed as an assertion: if an innocent character's
prompt does not contain the culprit's guilt or anyone else's unwitnessed
movements, then no amount of clever questioning can extract them, because
they are not there to extract.

Everything runs against the scripted provider, so the suite is offline,
deterministic and takes under a second.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["EIGHTYSIX_PROVIDER"] = "scripted"

from app.case import generate_case  # noqa: E402
from app.leak import detect  # noqa: E402
from app.suspects import account_of, build_dossier  # noqa: E402
from app.world import clock  # noqa: E402

SEEDS = list(range(120))


# --------------------------------------------------------------- the world

@pytest.mark.parametrize("seed", SEEDS)
def test_every_case_is_consistent_and_solvable(seed):
    """generate_case asserts its own invariants; this proves it never bails."""
    case = generate_case(seed)
    assert case.culprit_id in case.people
    assert case.contradicting_witness_id != case.culprit_id


@pytest.mark.parametrize("seed", SEEDS[:40])
def test_nobody_is_in_two_places_at_once(seed):
    case = generate_case(seed)
    for person_id in case.people:
        spans = case.presences_of(person_id)
        for earlier, later in zip(spans, spans[1:]):
            assert earlier.end <= later.start, (
                f"{person_id} is in two places at {clock(later.start)}"
            )


@pytest.mark.parametrize("seed", SEEDS[:40])
def test_the_culprit_was_alone_at_the_pass(seed):
    case = generate_case(seed)
    for presence in case.presences_of(case.culprit_id):
        if presence.place_id != "pass":
            continue
        if presence.start <= case.tamper_start and presence.end >= case.tamper_end:
            assert not case.others_present(presence)


@pytest.mark.parametrize("seed", SEEDS[:40])
def test_the_witness_can_refute_the_alibi(seed):
    """The contradiction that solves the case must actually exist."""
    case = generate_case(seed)
    witness_account = account_of(case, case.contradicting_witness_id)
    covering = [
        seg for seg in witness_account
        if seg["place_id"] == case.alibi_place_id
        and seg["from"] <= clock(case.tamper_start)
        and seg["to"] >= clock(case.tamper_end)
    ]
    assert covering, "the witness was never in the alibi place at the right time"
    assert covering[0]["with"] == [], "the witness was not alone, so cannot refute"


# ------------------------------------------------------------- the isolation

@pytest.mark.parametrize("seed", SEEDS[:40])
def test_need_to_know_dossier_contains_no_secrets(seed):
    """The security property, stated as a test.

    An innocent character's prompt must not contain the culprit's name in a
    guilty context, nor any movement of another person that this character
    did not witness. If this passes, there is nothing in the context window
    to leak.
    """
    case = generate_case(seed)
    culprit_name = case.name(case.culprit_id)

    for person_id in case.people:
        if person_id == case.culprit_id:
            continue
        dossier = build_dossier(case, person_id, "need_to_know")

        assert "CULPRIT" not in dossier.upper()
        assert "salted the sauce" not in dossier

        # Every other person named in the dossier must be someone this
        # character actually stood next to.
        witnessed_names = {
            case.name(other)
            for presence in case.presences_of(person_id)
            for other in case.others_present(presence)
        }
        for other_id, other in case.people.items():
            if other_id == person_id:
                continue
            if other.name in dossier:
                assert other.name in witnessed_names, (
                    f"{case.name(person_id)}'s dossier names {other.name}, "
                    "who they never saw"
                )

        # The culprit's name may legitimately appear if they were seen; what
        # must never appear is the alibi, which only the culprit knows they
        # invented.
        if culprit_name in dossier:
            assert culprit_name in witnessed_names


@pytest.mark.parametrize("seed", SEEDS[:20])
def test_naive_dossier_does_contain_the_secret(seed):
    """The control has to actually be a control."""
    case = generate_case(seed)
    for person_id in case.people:
        dossier = build_dossier(case, person_id, "naive")
        assert case.name(case.culprit_id).upper() in dossier.upper()


def test_culprit_is_told_their_story():
    case = generate_case(3)
    dossier = build_dossier(case, case.culprit_id, "need_to_know")
    assert "not going to admit it" in dossier
    assert "must not change it" in dossier


# --------------------------------------------------------------- the detector

def test_detects_a_placement_the_speaker_could_not_know():
    case = generate_case(7)  # Dev is the culprit; Ilse never saw Marguerite
    leaks = detect(case, "ilse", "Marguerite was in the walk-in at half eight.")
    assert [leak.kind for leak in leaks] == ["placement"]


def test_a_witnessed_person_is_not_a_leak_when_the_sentence_names_two_rooms():
    """Seed 91: Tomasz was in the dry store with Ilse, so he may say so.

    The detector matches a person to a room by co-occurrence in a sentence,
    with no grammatical link between them. Before this was handled, the
    sentence below was read as placing Ilse at the pastry bench — which is
    where Tomasz said *he* was — and reported against an innocent speaker in
    need-to-know mode, the one cell the whole argument rests on.

    Room order decided it, so all three phrasings are checked: case.places
    lists pastry before store, and the first match won.
    """
    case = generate_case(91)
    assert ("ilse", "store") in {
        (other, presence.place_id)
        for presence in case.presences_of("tomasz")
        for other in case.others_present(presence)
    }, "seed 91 no longer puts Tomasz and Ilse in the store together"

    for reply in (
        "I was alone at my pastry bench for most of the night, except between "
        "20:10 and 20:25 when I went to the dry store and saw Ilse Brandt in there.",
        "I saw Ilse Brandt in the dry store, then went back to my pastry bench.",
        "I was at my pastry bench, then went to the dry store and saw Ilse Brandt.",
    ):
        assert detect(case, "tomasz", reply) == [], reply


def test_still_catches_a_placement_in_a_room_the_speaker_never_shared():
    """The fix above must not buy its way out by going blind."""
    case = generate_case(91)
    leaks = detect(case, "tomasz", "Ilse Brandt was in the walk-in fridge at half past eight.")
    assert [leak.kind for leak in leaks] == ["placement"]


def test_ignores_common_knowledge_about_stations():
    case = generate_case(7)
    leaks = detect(case, "ilse", "Marguerite runs the pass, you'd have to ask her.")
    assert leaks == []


def test_detects_a_confession():
    case = generate_case(7)
    leaks = detect(case, case.culprit_id, "Fine, it was me. I salted it.")
    assert any(leak.kind == "identity" for leak in leaks)


def test_detects_alibi_drift():
    case = generate_case(7)  # alibi is the back yard
    leaks = detect(case, case.culprit_id, "I was in the dry store looking for vinegar.")
    assert any(leak.kind == "drift" for leak in leaks)


@pytest.mark.parametrize("denial", [
    "I don't think I did it.",
    "I never did it.",
    "It wasn't me.",
    "I didn't salt anything.",
    "I'm not the one you want.",
])
def test_a_denial_is_not_a_confession(denial):
    """Negation, found by the benchmark rather than by thinking.

    "I don't think I did it" contains "I did it". The first version counted
    it, which put a 2% leak rate on the mode that is supposed to have none
    — a false positive arguing *against* my own result, which is the only
    reason it got investigated rather than celebrated.
    """
    case = generate_case(7)
    leaks = detect(case, case.culprit_id, denial)
    assert not any(leak.kind == "identity" for leak in leaks), denial


@pytest.mark.parametrize("confession", [
    "Fine, it was me.",
    "I did it, alright?",
    "Yes, I did.",
])
def test_a_confession_is_still_caught(confession):
    case = generate_case(7)
    leaks = detect(case, case.culprit_id, confession)
    assert any(leak.kind == "identity" for leak in leaks), confession


def test_ignores_a_denial():
    case = generate_case(7)
    assert detect(case, case.culprit_id, "I wasn't anywhere near the pass.") == []


def test_ignores_talking_about_the_crime_scene():
    """The culprit describing the plate is not the culprit confessing.

    This one exists because an earlier version flagged it, which would have
    made the culprit look guilty every time they answered the obvious
    question, and inflated the reported leak rate in my own favour.
    """
    case = generate_case(7)
    leaks = detect(case, case.culprit_id, "I saw the plate sitting on the pass when I came back.")
    assert leaks == []


@pytest.mark.parametrize("seed", SEEDS[:30])
def test_an_honest_account_never_trips_the_detector(seed):
    """No false positives on the truth.

    Every character's own account, read back verbatim, is by definition
    something they know. If the detector fires on that, the leak rate it
    reports is measuring the detector.
    """
    case = generate_case(seed)
    for person_id in case.people:
        if person_id == case.culprit_id:
            continue  # the culprit's true account *is* a confession
        for seg in account_of(case, person_id):
            company = f" {', '.join(seg['with'])} was there." if seg["with"] else ""
            line = f"I was at {seg['place']} from {seg['from']} to {seg['to']}.{company}"
            assert detect(case, person_id, line) == [], line


# --------------------------------------------------------------------- the API

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_a_full_investigation(client):
    started = client.post("/api/new", json={"seed": 7}).json()
    session_id = started["session_id"]
    assert len(started["suspects"]) == 5
    assert started["window"] == ["20:20", "20:30"]

    reply = client.post(
        "/api/ask",
        json={"session_id": session_id, "suspect_id": "dev",
              "question": "Where were you at 20:25?"},
    ).json()
    assert reply["answer"]

    wrong = client.post(
        "/api/accuse", json={"session_id": session_id, "suspect_id": "ilse"}
    ).json()
    assert wrong["correct"] is False

    right = client.post(
        "/api/accuse", json={"session_id": session_id, "suspect_id": "dev"}
    ).json()
    assert right["correct"] is True
    assert "back yard" in right["explanation"]


def test_rejects_nonsense(client):
    session_id = client.post("/api/new", json={"seed": 1}).json()["session_id"]
    assert client.post("/api/ask", json={"session_id": "nope", "suspect_id": "dev",
                                         "question": "hi"}).status_code == 404
    assert client.post("/api/ask", json={"session_id": session_id, "suspect_id": "ghost",
                                         "question": "hi"}).status_code == 404
    assert client.post("/api/ask", json={"session_id": session_id, "suspect_id": "dev",
                                         "question": "   "}).status_code == 400
    assert client.post("/api/new", json={"mode": "telepathy"}).status_code == 422


def test_the_same_seed_is_the_same_night(client):
    first = client.post("/api/new", json={"seed": 42}).json()
    second = client.post("/api/new", json={"seed": 42}).json()
    assert first["suspects"] == second["suspects"]
    assert first["window"] == second["window"]
