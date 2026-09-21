"""The shape of the world.

Nothing here knows about language models. These are the types the case
generator fills in and the interrogation layer reads from, and the strict
separation is the point of the whole project: the truth lives in Python
objects, and a model is only ever handed a rendering of the small part of
them that one character is entitled to see.

The one rule this file exists to enforce: a character's knowledge is
*derived* from the world, never authored alongside it. If you write out
"what Dev knows" by hand, you will sooner or later write down something Dev
has no way of knowing, and the leak you are trying to measure will already
be in your ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Service runs 19:00 to 22:00. Everything internal is minutes since 19:00,
# because arithmetic on wall-clock strings is how off-by-one errors are born.
SERVICE_START_MIN = 0
SERVICE_END_MIN = 180


def clock(minute: int) -> str:
    """Minutes since service start -> '20:15'."""
    total = 19 * 60 + minute
    return f"{total // 60:02d}:{total % 60:02d}"


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    # Somewhere a person can plausibly be alone and unobserved. The culprit
    # needs one of these; so, unhelpfully for the player, do several innocent
    # people.
    private: bool = False
    # The other things kitchen staff call this room. The detector matches on
    # these, so they decide what it can see: a model that says "the cold
    # room" when the alias list only has "the walk-in fridge" has leaked and
    # got away with it.
    #
    # They are kept deliberately conservative. Adding bare "fish" or "pass"
    # would catch more real leaks and also fire on "the fish course" and
    # "pass me the tray" — and a false accusation would make the reported
    # leak rate higher than the truth, which is the one direction this
    # measurement must never be wrong in.
    aliases: tuple[str, ...] = ()

    def mentions(self) -> tuple[str, ...]:
        return (self.name.lower(), *(a.lower() for a in self.aliases))


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str
    station: str  # the place id they work from
    voice: str    # how they talk, handed to the model as character direction


@dataclass(frozen=True)
class Presence:
    """X was in this place from this minute to that minute. Ground truth."""

    person_id: str
    place_id: str
    start: int
    end: int

    def overlaps(self, other: "Presence") -> bool:
        return (
            self.place_id == other.place_id
            and self.start < other.end
            and other.start < self.end
        )


@dataclass
class Case:
    """One generated case. Everything true about the night is in here."""

    seed: int
    places: dict[str, Place]
    people: dict[str, Person]
    presences: list[Presence]

    culprit_id: str
    # When the sauce was tampered with. Known to the player from the start,
    # because the kitchen printer timestamps every ticket — the window is
    # evidence, not a secret.
    tamper_start: int
    tamper_end: int
    tamper_place_id: str

    # The lie the culprit has decided to tell, fixed before anyone asks. It
    # has to be fixed rather than improvised, or the character contradicts
    # itself between turns and the puzzle becomes unsolvable noise rather
    # than a mystery.
    alibi_place_id: str
    # The person who was genuinely in the alibi place and will say they were
    # alone. This contradiction is the solution.
    contradicting_witness_id: str

    motives: dict[str, str] = field(default_factory=dict)

    # ---------------------------------------------------------------- views

    def presences_of(self, person_id: str) -> list[Presence]:
        return sorted(
            (p for p in self.presences if p.person_id == person_id),
            key=lambda p: p.start,
        )

    def others_present(self, presence: Presence) -> set[str]:
        """Who else was in the room, by the rules of space and time."""
        return {
            other.person_id
            for other in self.presences
            if other.person_id != presence.person_id and other.overlaps(presence)
        }

    def witnesses_for(self, person_id: str, start: int, end: int) -> set[str]:
        """Anyone who can place this person somewhere during a window."""
        window = Presence(person_id, "", start, end)
        seen_by: set[str] = set()
        for presence in self.presences_of(person_id):
            if presence.start < window.end and window.start < presence.end:
                seen_by |= self.others_present(presence)
        return seen_by

    def name(self, person_id: str) -> str:
        return self.people[person_id].name

    def place_name(self, place_id: str) -> str:
        return self.places[place_id].name
