"""Run the prose -> Pony translator over tests/translate_eval.json and score it.

    .venv/bin/python tests/eval_translate.py [--mode local|rules|auto|remote] [-v]

`must`: each entry is a tag or alternatives separated by "|" (any one present counts).
`must_not`: tags that must not appear (matched against whole tags, so "hair" does not hit "long hair").
Targets: local >= 85% recall, rules >= 55%, zero must_not hits for both.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nekostudio.prompts import translate as tr  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="local", choices=["auto", "local", "rules", "remote"])
    ap.add_argument("--file", default=str(ROOT / "tests" / "translate_eval.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    cases = json.loads(Path(a.file).read_text("utf-8"))
    hit_total = must_total = bad_total = 0
    times = []
    for i, c in enumerate(cases, 1):
        t0 = time.time()
        r = tr.translate(c["text"], a.mode, "anime", "safe")
        dt = time.time() - t0
        times.append(dt)
        tags = set(r["tags"])
        missing = [m for m in c["must"] if not any(alt.strip() in tags for alt in m.split("|"))]
        bad = [m for m in c.get("must_not", []) if m in tags]
        hit = len(c["must"]) - len(missing)
        hit_total += hit
        must_total += len(c["must"])
        bad_total += len(bad)
        print(f"[{i}] recall {hit}/{len(c['must'])} ({100 * hit // len(c['must'])}%)  must_not hits: {bad or 0}  {dt:.1f}s  engine={r.get('engine')}")
        print(f"    prompt : {r['prompt']}")
        if missing:
            print(f"    missing: {missing}")
        if a.verbose:
            print(f"    dropped: {r['dropped']}\n    fixed  : {[(f['from'], f['to']) for f in r.get('fixed', [])]}")
    pct = 100 * hit_total / must_total
    print(f"\nTOTAL mode={a.mode}: recall {hit_total}/{must_total} = {pct:.1f}%   must_not hits: {bad_total}   avg {sum(times) / len(times):.1f}s/translation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
