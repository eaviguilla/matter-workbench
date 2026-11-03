"""Compare the app's onnxruntime backend with the gliner library on the synthetic transcripts.

Run this once after every export. It needs the export extras (gliner, torch).
Exit code 1 if the two disagree on any span.

  python scripts/check_onnx_parity.py --model urchade/gliner_multi_pii-v1 --out models/gliner_pii
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.scrub.evaluate import load_annotated  # noqa: E402
from app.scrub.ner import LABELS, OnnxGlinerBackend, find_model_file  # noqa: E402
from app.scrub.parse import parse_transcript  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()
    from gliner import GLiNER
    ref = GLiNER.from_pretrained(args.model)
    mf = find_model_file(Path(args.out))
    mine = OnnxGlinerBackend(mf.parent, mf.name)
    diffs = checked = 0
    for f in sorted((ROOT / "tests" / "fixtures").glob("*.ann.txt")):
        ann = load_annotated(f.stem, f.read_text(encoding="utf-8"))
        for t in parse_transcript(ann.text).turns:
            body = ann.text[t.body_span[0]:t.body_span[1]]
            a = {(e["start"], e["end"], e["label"]) for e in ref.predict_entities(body, list(LABELS), threshold=args.threshold)}
            b = {(h.start, h.end, h.label) for h in mine.predict(body, LABELS, args.threshold)}
            checked += 1
            if a != b:
                diffs += 1
                print(f"{f.stem} turn at line {t.line}: only gliner {sorted(a - b)}  only app {sorted(b - a)}")
    print(f"{checked} turns checked, {diffs} differ")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
