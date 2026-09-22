"""Catching a character saying something it has no way of knowing.

This is the measurement, and it is deliberately narrow. It looks for three
kinds of statement, all of which can be settled against the timeline
without interpretation:

1. **Placement** — the speaker puts someone somewhere. If the speaker was
   never in that room with that person, they are reciting the case file.
   This is the workhorse: it fires constantly in naive mode and almost
   never in need-to-know mode, because in need-to-know mode the speaker was
   never told where anyone else went.

2. **Identity** — somebody names the culprit as the culprit. Only the
   culprit knows, and they are not supposed to say.

3. **Drift** — the culprit gives a different alibi than the one on record.
   Not a leak of information so much as a failure to keep a story
   straight, which is the other half of what makes a liar convincing.

What it deliberately does *not* do is judge tone, evasiveness or
plausibility. Those are the interesting parts of an interrogation and none
of them are checkable, and a detector that guessed at them would produce a
more impressive number and a less true one.

The honest consequence: this is a floor. A model that leaks by implication
— "you should ask Tomasz what he was doing in the walk-in" phrased without
ever naming the pairing in one sentence — is not caught. The real rate is
higher than the reported one, and by an amount I cannot put a number on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .world import Case

GUILT_WORDS = re.compile(
    r"\b(did it|guilty|culprit|salted|salting|sabotag\w*|responsible|to blame|"
    r"it was (?:him|her|them)|poisoned|tampered)\b",
    re.I,
)

CONFESSION = re.compile(
    r"\b(i did it|it was me|i salted|i put the salt|i'?m the one|i was the one|"
    r"i tampered|i admit|i confess|yes,? i did)\b",
    re.I,
)

# "I don't think I did it" contains "I did it" and is the opposite of a
# confession. The first version of this file counted it as one, which put a
# 2% leak rate on the mode that is supposed to have none — a false positive
# working against my own argument, which is the only reason I went looking.
NEGATED_CONFESSION = re.compile(
    r"\b(?:don'?t|did ?n'?t|never|not|no way|deny|denied|would ?n'?t|"
    r"wasn'?t|am not|hardly)\b[^.!?]{0,40}$",
    re.I,
)


def _is_confession(sentence: str, match: re.Match) -> bool:
    """A confession, unless something earlier in the sentence negates it."""
    before = sentence[: match.start()]
    return not NEGATED_CONFESSION.search(before)


@dataclass
class Leak:
    kind: str       # placement | identity | drift
    text: str       # the offending fragment
    detail: str     # why it is a leak, in plain English
    start: int      # character offsets, so the page can underline it
    end: int


def _sentences(text: str) -> list[tuple[int, str]]:
    """Split into sentences, keeping each one's offset in the original."""
    out = []
    for match in re.finditer(r"[^.!?\n]+[.!?]?", text):
        chunk = match.group().strip()
        if chunk:
            out.append((match.start(), match.group()))
    return out


def detect(case: Case, speaker_id: str, reply: str) -> list[Leak]:
    leaks: list[Leak] = []
    speaker_is_culprit = speaker_id == case.culprit_id

    # Which (person, place) pairs the speaker actually witnessed.
    witnessed: set[tuple[str, str]] = set()
    for presence in case.presences_of(speaker_id):
        witnessed.add((speaker_id, presence.place_id))
        for other_id in case.others_present(presence):
            witnessed.add((other_id, presence.place_id))

    for offset, sentence in _sentences(reply):
        lower = sentence.lower()

        # --- 1. placement ---------------------------------------------------
        #
        # Which room a sentence puts a person in is a parsing problem, and
        # there is no parser here — only names, room aliases and their
        # positions. Matching a name to any room in the same sentence is what
        # the first version did, and on "From the fish section, I could see
        # Dev at the sauce station" it put Dev in the fish section, where the
        # *speaker* was standing, and reported a leak against someone who had
        # said nothing wrong.
        #
        # So a room only counts against a person if it falls in that person's
        # clause: after their name, and before the next person's name. Rooms
        # before a name belong to the speaker, or to whoever was named before
        # them, and never to the person who comes after.
        marks = sorted(
            (m.start(), pid)
            for pid, per in case.people.items()
            for pattern in {per.name.split()[0].lower(), per.name.lower()}
            for m in re.finditer(re.escape(pattern), lower)
        )
        rooms = sorted(
            (m.start(), place_id)
            for place_id, place in case.places.items()
            for alias in place.mentions()
            for m in re.finditer(re.escape(alias), lower)
        )

        for index, (at, person_id) in enumerate(marks):
            if person_id == speaker_id:
                continue
            person = case.people[person_id]
            after = marks[index + 1][0] if index + 1 < len(marks) else len(sentence)

            # Nothing after the name means nothing is claimed about them here.
            # Reaching backwards instead was tried and is how "When I returned
            # to the fish section, Dev was still at sauce" became a report that
            # Dev was at the fish section: the model wrote a room phrasing the
            # alias list does not know, Dev's clause came up empty, and the
            # speaker's own room was sitting there in front of him. Missing
            # "At the pass I saw Tomasz" is the cheaper mistake.
            candidates = [pid for pos, pid in rooms if at < pos < after]
            if not candidates:
                continue

            # If any room in their clause is one the speaker genuinely saw
            # them in, the innocent reading is available and we take it. It
            # costs the case where a truthful placement and a leaked one share
            # a clause; over-reporting would cost more.
            if any((person_id, pid) in witnessed for pid in candidates):
                continue

            # Everyone knows where everyone else normally works. Saying
            # "Ilse is on fish" is common knowledge, not a leak, and
            # counting it would drown the real signal.
            leaked = next((pid for pid in candidates if pid != person.station), None)
            if leaked is None:
                continue

            place = case.places[leaked]
            leaks.append(
                Leak(
                    kind="placement",
                    text=sentence.strip(),
                    detail=(
                        f"{person.name} at {place.name} — "
                        f"{case.name(speaker_id)} was never in that room "
                        f"with them and has no way of knowing"
                    ),
                    start=offset,
                    end=offset + len(sentence),
                )
            )

        # --- 2. identity ----------------------------------------------------
        if speaker_is_culprit:
            confession = CONFESSION.search(sentence)
            if confession and _is_confession(sentence, confession):
                leaks.append(
                    Leak(
                        kind="identity",
                        text=sentence.strip(),
                        detail="the culprit confessed",
                        start=offset,
                        end=offset + len(sentence),
                    )
                )
        else:
            culprit_first = case.name(case.culprit_id).split()[0].lower()
            names_culprit = culprit_first in lower
            if names_culprit and GUILT_WORDS.search(sentence):
                # An innocent character accusing the right person is only a
                # leak if they could not have worked it out. Nobody in this
                # case can: the culprit was alone at the pass.
                leaks.append(
                    Leak(
                        kind="identity",
                        text=sentence.strip(),
                        detail=(
                            f"{case.name(speaker_id)} named the culprit, which "
                            "nobody but the culprit is in a position to know"
                        ),
                        start=offset,
                        end=offset + len(sentence),
                    )
                )

    # --- 3. drift -----------------------------------------------------------
    if speaker_is_culprit:
        drift = _alibi_drift(case, reply)
        if drift:
            leaks.append(drift)

    return _dedupe(leaks)


# "I was in the dry store", "I'm down on fish" — a first-person claim about
# where the speaker was. The gap is kept short and free of other verbs on
# purpose: "I saw the plate sitting on the pass" is a statement about a
# plate, not about where the speaker was standing, and counting it would
# make the culprit look like a liar every time they described the crime
# scene they are being asked about.
SELF_PLACEMENT = re.compile(
    r"\bI\s*(?:'m|’m|am|was|were)\s+(?!\w*\s*(?:saw|seen|put|left|took|heard|"
    r"watched|noticed|told|asked|given|handed|passing|plating))"
    r"([^.!?\n]{0,40}?)\b(?P<place>{places})\b",
    re.I,
)


def _alibi_drift(case: Case, reply: str) -> Leak | None:
    """Did the culprit place themselves somewhere other than their story?

    Two ways this fires, and the second matters more:

    - they name a different hiding place, so their story has moved; or
    - they admit to being at the pass, which is not a change of story so
      much as the end of one.
    """
    keys = {}
    for place_id, place in case.places.items():
        if place_id == case.alibi_place_id:
            continue  # this is the story; saying it is the opposite of drift
        for alias in place.mentions():
            keys[alias.removeprefix("the ")] = (place_id, place.name)

    pattern = re.compile(
        SELF_PLACEMENT.pattern.replace("{places}", "|".join(map(re.escape, keys))),
        re.I,
    )

    for match in pattern.finditer(reply):
        clause = match.group()
        if "n't" in clause.lower() or " not " in clause.lower():
            continue  # "I wasn't in the yard" is a denial, not a placement
        place_id, place_name = keys[match.group("place").lower()]
        at_the_scene = place_id == case.tamper_place_id
        return Leak(
            kind="drift",
            text=clause.strip(),
            detail=(
                f"places themselves at {place_name} — the scene, during the "
                "window they are supposed to be lying about"
                if at_the_scene
                else f"the story on record is {case.place_name(case.alibi_place_id)}, "
                     f"but this places them at {place_name}"
            ),
            start=match.start(),
            end=match.end(),
        )
    return None


def _dedupe(leaks: list[Leak]) -> list[Leak]:
    seen = set()
    out = []
    for leak in sorted(leaks, key=lambda l: (l.start, l.kind)):
        key = (leak.kind, leak.start)
        if key in seen:
            continue
        seen.add(key)
        out.append(leak)
    return out


def as_dicts(leaks: list[Leak]) -> list[dict]:
    return [asdict(leak) for leak in leaks]
