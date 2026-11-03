"""One-off: download a GLiNER checkpoint, check its license, export it to int8 ONNX.

This is the only place that touches the network, and the app never imports it.
Needs the export extras (torch lives only here):  pip install -e ".[export]"

  python scripts/export_onnx.py --model urchade/gliner_multi_pii-v1 --out models/gliner_pii
"""
import argparse
import json
import sys
from pathlib import Path

ALLOWED_LICENSES = {"apache-2.0", "mit"}


def quantize_embeddings(src: Path, dst: Path) -> None:
    """int8 for the embedding table only. The table is two thirds of the weights. Quantizing the
    DeBERTa matrix multiplies as well (gliner's default) cut scores from 1.0 to about 0.5, which
    breaks the 0.5 threshold, so those stay in full precision."""
    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(src), str(dst), op_types_to_quantize=["Gather"], weight_type=QuantType.QInt8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Hugging Face repo id of a GLiNER span model")
    ap.add_argument("--out", default="models/gliner", help="output folder (gitignored)")
    ap.add_argument("--keep-fp32", action="store_true", help="keep the 1.1 GB full-precision model.onnx")
    ap.add_argument("--check-license-only", action="store_true", help="read the model card and stop")
    args = ap.parse_args()

    from huggingface_hub import model_info
    info = model_info(args.model)
    license_ = (getattr(info.card_data, "license", None) or "unknown").lower()
    print(f"{args.model}: license {license_}")
    if license_ not in ALLOWED_LICENSES:
        print(f"Refusing: license {license_!r} is not one of {sorted(ALLOWED_LICENSES)}. Check it by hand first.")
        return 2
    if args.check_license_only:
        return 0

    from gliner import GLiNER
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model = GLiNER.from_pretrained(args.model)
    model.export_to_onnx(str(out), onnx_filename="model.onnx", quantize=False)
    quantize_embeddings(out / "model.onnx", out / "model_quantized.onnx")
    if not args.keep_fp32:
        (out / "model.onnx").unlink()
    # The runtime backend reads these two files, so keep them next to the model.
    tok = model.data_processor.transformer_tokenizer
    tok.save_pretrained(str(out))                       # writes tokenizer.json for fast tokenizers
    cfg = {"max_width": model.config.max_width, "max_len": model.config.max_len,
           "ent_token": model.config.ent_token, "sep_token": model.config.sep_token,
           "source_model": args.model, "license": license_}
    (out / "gliner_config.json").write_text(json.dumps(cfg, indent=2))
    if not (out / "tokenizer.json").is_file():
        print("tokenizer.json missing; the model's tokenizer is not a fast tokenizer.")
        return 3
    print(f"Wrote {out}. Run scripts/check_onnx_parity.py --model {args.model} --out {out} next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
