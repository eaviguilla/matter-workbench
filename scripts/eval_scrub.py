"""Score the scrubber on the synthetic conversations.

  python scripts/eval_scrub.py                 # summary for every fixture
  python scripts/eval_scrub.py --show 3        # also print the scrubbed text of fixture 3
  python scripts/eval_scrub.py --keep-first    # leave first names in plain text
  python scripts/eval_scrub.py --model-dir models/gliner_pii --threshold 0.5   # add the NER stage

Exit code 1 if any tagged value is still visible after the review gate.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.scrub.evaluate import evaluate, load_annotated  # noqa: E402
from app.scrub.ner import NerConfig, NerModel  # noqa: E402
from app.scrub.pipeline import ScrubConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "tests" / "fixtures"))
    ap.add_argument("--keep-first", action="store_true")
    ap.add_argument("--model-dir", help="folder with the exported ONNX model; turns the NER stage on")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--show", type=int, help="print the scrubbed text of fixture N (1-based)")
    args = ap.parse_args()
    cfg = ScrubConfig(keep_first_names=args.keep_first)
    ner = NerModel(NerConfig(model_dir=Path(args.model_dir), threshold=args.threshold)) if args.model_dir else None
    if ner is not None and not ner.available:
        print(f"No model in {args.model_dir}")
        return 2
    files = sorted(Path(args.dir).glob("*.ann.txt"))
    totals, missed, caught, bad, exempt = {}, 0, 0, 0, 0
    for i, f in enumerate(files, 1):
        rep = evaluate(load_annotated(f.stem, f.read_text(encoding="utf-8")), cfg, ner)
        for t, n in rep.total.items():
            totals[t] = totals.get(t, 0) + n
        miss = rep.auto_missed
        exempt += rep.exempt
        missed += len(miss)
        caught += sum(1 for m in miss if m[2])
        bad += len(rep.leaks_after_gate) + len(rep.inconsistent)
        print(f"{i:2} {f.stem:28} tagged={sum(rep.total.values()):3} missed={len(miss):2} "
              f"flags={rep.flags:2} over={len(rep.over_scrubbed):2} inconsistent={len(rep.inconsistent)}")
        for t, text, c in miss:
            print(f"     MISSED {t:8} {text!r}{'  (flagged)' if c else '  (NOT flagged)'}")
        for msg in rep.inconsistent:
            print(f"     INCONSISTENT {msg}")
        if rep.over_scrubbed:
            print(f"     over-scrubbed: {sorted(set(rep.over_scrubbed))}")
        if args.show == i:
            print("\n" + rep.scrubbed_text + "\n")
    n = sum(totals.values()) - exempt
    print(f"\ntagged {sum(totals.values())} {totals}; {exempt} first names intentionally kept; "
          f"auto recall over the {n} values that must be scrubbed {(n - missed) / n:.1%}; "
          f"missed {missed}, of which {caught} flagged for review; problems after gate: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
