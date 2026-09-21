"""Generating a night that actually happened.

The generator has two jobs and they pull against each other.

It must produce a world that is *consistent* — nobody in two places at once,
every witness statement derivable from the same timeline — and it must
produce one that is *solvable*, meaning exactly one thread comes loose when
you pull it.

Consistency is easy: build the timeline first and derive everything else
from it. Solvability is the hard half, and it is why this file ends with an
assertion rather than a return. A generator that quietly emits an unsolvable
case is worse than one that crashes, because you find out during a demo.

The design: everybody works a station. Everybody leaves it once, because
people do. The culprit leaves it twice — once openly, once to walk to the
pass while nobody is there — and then claims the second trip was somewhere
else. That claimed somewhere-else is occupied by exactly one other person,
who will tell you they were alone.

That is the whole puzzle. One contradiction, reachable by asking two people
the same question.
"""

from __future__ import annotations

import random

from .world import SERVICE_END_MIN, Case, Person, Place, Presence

PLACES = [
    Place("pass", "the pass", aliases=("the pass", "on the pass", "at the pass")),
    Place("sauce", "the sauce section", aliases=("on sauce", "sauce section", "the sauce station")),
    Place("fish", "the fish section", aliases=("on fish", "fish section", "the fish station")),
    Place("pastry", "the pastry bench", aliases=("pastry bench", "the pastry section", "on pastry")),
    Place("walkin", "the walk-in fridge", private=True,
          aliases=("walk-in", "walkin", "walk in", "the cold room", "the fridge")),
    Place("store", "the dry store", private=True,
          aliases=("dry store", "the store", "the stores", "storeroom", "store room")),
    Place("yard", "the back yard", private=True,
          aliases=("the yard", "backyard", "out back", "the bins")),
    Place("dining", "the dining room", aliases=("dining room", "the floor", "front of house", "out front")),
]

# Places somebody might credibly disappear to for ten minutes mid-service.
EXCURSION_PLACES = ["walkin", "store", "yard"]

PEOPLE = [
    Person(
        "marguerite", "Marguerite Okonjo", "head chef", "pass",
        "Clipped. Answers in as few words as the question allows. Has run "
        "this kitchen for nine years and resents being asked to account for "
        "herself in it.",
    ),
    Person(
        "dev", "Dev Raman", "sous chef", "sauce",
        "Talks quickly and too much, fills silences, apologises for things "
        "that are not his fault. Desperate to be helpful.",
    ),
    Person(
        "ilse", "Ilse Brandt", "chef de partie, fish", "fish",
        "Flat and factual. Volunteers nothing. Treats every question as a "
        "request for the minimum true answer.",
    ),
    Person(
        "tomasz", "Tomasz Wierzbicki", "pastry chef", "pastry",
        "Warm, digressive, tells you about the weather and his sister. "
        "Genuinely friendly and genuinely hard to keep on topic.",
    ),
    Person(
        "cal", "Cal Feeney", "maître d'", "dining",
        "Smooth, front-of-house polish, deflects with charm. Used to "
        "managing people who are unhappy about something.",
    ),
]

MOTIVES = {
    "marguerite": "The guide inspection was her idea. A second star would "
                  "have doubled her worth to the group; losing the first one "
                  "makes her a liability.",
    "dev": "He was passed over for the sous position twice before he got it, "
           "and has been told the kitchen is 'not ready' for his menu.",
    "ilse": "She handed in her notice three weeks ago and is opening forty "
            "miles away. A wounded reputation here is worth customers there.",
    "tomasz": "His dessert was cut from the tasting menu in March to make "
              "room for the dish that went to table nine.",
    "cal": "He is owed four months of service charge and has stopped asking "
           "for it politely.",
}

ALIBI_PHRASING = {
    "walkin": "in the walk-in, checking the fish delivery",
    "store": "in the dry store, looking for the good vinegar",
    "yard": "out in the yard, getting some air",
    "pastry": "over at the pastry bench",
    "fish": "down on fish, helping out",
    "dining": "out front in the dining room",
    "sauce": "on sauce",
}


def generate_case(seed: int) -> Case:
    """Build one consistent, solvable night. Same seed, same night."""
    rng = random.Random(seed)

    places = {p.id: p for p in PLACES}
    people = {p.id: p for p in PEOPLE}
    ids = list(people)

    # --- 1. the tampering window ------------------------------------------
    #
    # Fixed by the ticket printer, so the player is told it. Everything else
    # is arranged around it.
    tamper_start = rng.choice([70, 75, 80, 85])  # 20:10 – 20:25
    tamper_end = tamper_start + 10

    culprit_id = rng.choice(ids)
    others = [i for i in ids if i != culprit_id]

    # --- 2. the alibi, chosen before the timeline ---------------------------
    #
    # Picking the lie first and then building a world in which it is false is
    # far more reliable than building a world and hunting for a lie that fits
    # it. The witness is whoever will be standing in the place the culprit
    # claims to have been.
    witness_id = rng.choice(others)
    alibi_place_id = rng.choice(EXCURSION_PLACES)

    presences: list[Presence] = []

    def add(person_id: str, place_id: str, start: int, end: int) -> None:
        if end > start:
            presences.append(Presence(person_id, place_id, start, end))

    def excursion(person_id: str, place_id: str, start: int, end: int) -> None:
        """Leave the station, be somewhere, come back."""
        station = people[person_id].station
        add(person_id, station, 0, start)
        add(person_id, place_id, start, end)
        add(person_id, station, end, SERVICE_END_MIN)

    # Nobody innocent may wander into the place the culprit is about to claim.
    # If they did, they would corroborate the lie by accident, and the single
    # contradiction the case is built around would evaporate.
    other_excursions = [p for p in EXCURSION_PLACES if p != alibi_place_id]

    # --- 3. the witness is alone in the alibi place ------------------------
    #
    # Their window has to cover the tampering window completely. A partial
    # overlap would let the culprit say "you must have stepped out for a
    # second", and the one clean contradiction in the case would stop being
    # clean.
    excursion(witness_id, alibi_place_id, tamper_start - 5, tamper_end + 5)

    # --- 4. the culprit is at the pass, alone ------------------------------
    #
    # Two shapes, depending on who it turns out to be. The head chef works
    # the pass, so if it is her she simply stays put and lies about having
    # stepped out. Everyone else has to walk over.
    if people[culprit_id].station == "pass":
        add(culprit_id, "pass", 0, SERVICE_END_MIN)
    else:
        excursion(culprit_id, "pass", tamper_start, tamper_end)

    # --- 5. everyone else --------------------------------------------------
    #
    # Each gets one excursion. Some land inside the tampering window and some
    # do not, which is what stops the answer being "whoever left their
    # station". The red herrings are not decoration: without people who
    # cannot fully account for themselves and did nothing, the puzzle is one
    # question long.
    for person_id in others:
        if person_id == witness_id:
            continue

        if people[person_id].station == "pass":
            # The head chef, innocent. She must be away from the pass during
            # the tampering or she would have seen it happen — so her trip is
            # pinned to the window rather than scattered like the others'.
            excursion(person_id, rng.choice(other_excursions), tamper_start - 5, tamper_end + 5)
            continue

        trip_start = rng.choice([20, 35, 50, tamper_start, 110, 130])
        excursion(
            person_id,
            rng.choice(other_excursions),
            trip_start,
            trip_start + rng.choice([10, 15]),
        )

    case = Case(
        seed=seed,
        places=places,
        people=people,
        presences=presences,
        culprit_id=culprit_id,
        tamper_start=tamper_start,
        tamper_end=tamper_end,
        tamper_place_id="pass",
        alibi_place_id=alibi_place_id,
        contradicting_witness_id=witness_id,
        motives=dict(MOTIVES),
    )

    _assert_solvable(case)
    return case


def _assert_solvable(case: Case) -> None:
    """Refuse to hand back a case the player cannot crack.

    Three properties, each of which has been violated by a bug in this file
    at some point:

    1. Nobody saw the culprit at the pass. If they had, the mystery would be
       over before it started.
    2. The culprit's claimed alibi is contradicted — the witness was there
       and did not see them.
    3. The contradiction is *unique*. If two people's accounts fail to line
       up, the player has no way to tell which failure is the real one, and
       an unfair puzzle reads as a broken one.
    """
    culprit = case.culprit_id

    at_pass = [
        p for p in case.presences
        if p.place_id == "pass" and p.start < case.tamper_end and case.tamper_start < p.end
    ]
    assert {p.person_id for p in at_pass} == {culprit}, (
        f"seed {case.seed}: the pass was not empty during the tampering"
    )

    witness_presences = [
        p for p in case.presences_of(case.contradicting_witness_id)
        if p.place_id == case.alibi_place_id
    ]
    assert witness_presences, f"seed {case.seed}: the witness was never in the alibi place"
    w = witness_presences[0]
    assert w.start <= case.tamper_start and w.end >= case.tamper_end, (
        f"seed {case.seed}: the witness does not cover the whole tampering window"
    )
    assert not case.others_present(w), (
        f"seed {case.seed}: the witness was not alone, so the denial is not decisive"
    )

    # The witness is the *only* honest person who places themselves there.
    # If anyone else does, they corroborate the culprit's lie by accident and
    # the contradiction stops being decisive.
    claimants = {
        person_id for person_id in case.people
        if person_id != culprit and _claimed_place(case, person_id) == case.alibi_place_id
    }
    assert claimants == {case.contradicting_witness_id}, (
        f"seed {case.seed}: expected only the witness in the alibi place during "
        f"the window, got {sorted(claimants)}"
    )

    # And the culprit must not be where they say they were, or there is no lie.
    assert _claimed_place(case, culprit) == "pass", (
        f"seed {case.seed}: the culprit was not actually at the pass"
    )


def _claimed_place(case: Case, person_id: str) -> str | None:
    """Where an innocent person will truthfully say they were, at the time."""
    for presence in case.presences_of(person_id):
        if presence.start <= case.tamper_start < presence.end:
            return presence.place_id
    return None


def briefing(case: Case) -> dict:
    """What the player is told at the start. No secrets in here."""
    return {
        "title": "Eighty-Six",
        "subtitle": "Saturday service. Table nine. One scoop of salt.",
        "blurb": (
            "The guide inspector was on table nine and nobody was supposed to "
            "know. The sauce that went out with her main course had roughly a "
            "hundred grams of salt in it. The kitchen printer timestamps every "
            f"ticket, so the window is not in doubt: the sauce was clean at "
            f"{_clock(case.tamper_start)} and ruined by {_clock(case.tamper_end)}. "
            "It sat on the pass for those ten minutes. Five people were working. "
            "One of them walked over to it."
        ),
        "window": [_clock(case.tamper_start), _clock(case.tamper_end)],
        "suspects": [
            {
                "id": p.id,
                "name": p.name,
                "role": p.role,
                "station": case.place_name(p.station),
                "motive": case.motives.get(p.id, ""),
            }
            for p in case.people.values()
        ],
        "places": [{"id": p.id, "name": p.name} for p in case.places.values()],
    }


def _clock(minute: int) -> str:
    from .world import clock

    return clock(minute)
