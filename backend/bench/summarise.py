"""Reading the results.

    python bench/summarise.py

Three numbers, in descending order of how much they matter.

**Identity leaks** are the only catastrophic failure: somebody said who did
it. Everything else spoils the game; this ends it.

**Any leak** is the honest headline — a statement the speaker had no basis
for, of any kind. It is the number to quote.

**By question** is the diagnostic, and the interesting one. If the leak rate
climbs with how adversarial the question is, the model is being talked out
of the secret. If it is flat and high, the model is simply reciting its
context and would have done so unprompted.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.case import generate_case  # noqa: E402
from app.leak import detect  # noqa: E402

RESULTS = HERE / "results.jsonl"

MODES = ["need_to_know", "naive"]
LABEL = {"need_to_know": "Need-to-know", "naive": "Whole case file"}


def main() -> None:
    rows = [
        json.loads(line)
        for line in RESULTS.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if not r.get("error")]
    if not rows:
        print("no results yet — run bench/run.py")
        return

    # Re-run detection over the stored answers rather than trusting the
    # `kinds` recorded at generation time.
    #
    # Generating 180 answers takes a quarter of an hour; detecting on them
    # takes a fraction of a second. Keeping the raw text means every
    # improvement to the detector — and there have been several, including
    # one that was inflating the headline in my own favour — can be applied
    # to the existing results without spending the time again. The stored
    # `kinds` are only there so the live run prints something useful.
    cases = {seed: generate_case(seed) for seed in {r["seed"] for r in rows}}
    for row in rows:
        leaks = detect(cases[row["seed"]], row["suspect"], row["answer"])
        row["leaks"] = [{"kind": l.kind, "detail": l.detail} for l in leaks]
        row["kinds"] = sorted({l.kind for l in leaks})

    provider = rows[0].get("provider", "?")
    seeds = sorted({r["seed"] for r in rows})

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)

    print(f"provider: {provider} · cases: {seeds} · answers: {len(rows)}")
    print()
    print(f"{'':<18}{'answers':>9}{'any leak':>11}{'identity':>11}{'placement':>12}{'drift':>8}")

    summary = {}
    for mode in MODES:
        batch = by_mode.get(mode, [])
        if not batch:
            continue
        total = len(batch)
        counts = Counter()
        for row in batch:
            for kind in row["kinds"]:
                counts[kind] += 1
        any_leak = sum(1 for row in batch if row["kinds"])

        summary[mode] = {
            "answers": total,
            "any_leak": any_leak,
            "any_leak_rate": any_leak / total,
            "identity": counts["identity"],
            "placement": counts["placement"],
            "drift": counts["drift"],
        }
        print(
            f"{LABEL[mode]:<18}{total:>9}"
            f"{f'{any_leak} ({any_leak / total:.0%})':>11}"
            f"{counts['identity']:>11}{counts['placement']:>12}{counts['drift']:>8}"
        )

    # --- the diagnostic --------------------------------------------------
    print()
    print("by question, share of answers that leaked something:")
    question_ids = []
    for row in rows:
        if row["question_id"] not in question_ids:
            question_ids.append(row["question_id"])

    print(f"{'':<14}" + "".join(f"{q:>12}" for q in question_ids))
    by_question = {}
    for mode in MODES:
        cells = []
        for qid in question_ids:
            batch = [r for r in by_mode.get(mode, []) if r["question_id"] == qid]
            if not batch:
                cells.append("—")
                continue
            leaked = sum(1 for r in batch if r["kinds"])
            cells.append(f"{leaked / len(batch):.0%}")
            by_question.setdefault(mode, {})[qid] = leaked / len(batch)
        print(f"{LABEL[mode]:<14}" + "".join(f"{c:>12}" for c in cells))

    # --- who leaked ------------------------------------------------------
    #
    # The split that matters. Need-to-know cannot stop the culprit giving
    # themselves away, because the culprit is the one character who has to
    # know. What it can do is make it impossible for the other four, and
    # that is the number to look at.
    print()
    who = {}
    for mode in MODES:
        batch = by_mode.get(mode, [])
        if not batch:
            continue
        innocent = [r for r in batch if not r["is_culprit"]]
        culprit = [r for r in batch if r["is_culprit"]]
        i_leaked = sum(1 for r in innocent if r["kinds"])
        c_leaked = sum(1 for r in culprit if r["kinds"])
        who[mode] = {
            "innocent_answers": len(innocent),
            "innocent_leaked": i_leaked,
            "culprit_answers": len(culprit),
            "culprit_leaked": c_leaked,
        }
        print(
            f"{LABEL[mode]:<18} innocents {i_leaked}/{len(innocent)} "
            f"({i_leaked / len(innocent):.0%}) · "
            f"culprit {c_leaked}/{len(culprit)} ({c_leaked / len(culprit):.0%})"
        )

    (HERE / "results.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "seeds": seeds,
                "answers": len(rows),
                "summary": summary,
                "by_question": by_question,
                "who_leaked": who,
                "question_order": question_ids,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
