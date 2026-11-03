"""GLiNER stage: finds names, addresses and emails the rules cannot.

NerModel wraps a backend. It loads the model on first use and frees it after an idle period.
The backend is a plain object with predict(text, labels, threshold), so tests use a fake and the
real one (OnnxGlinerBackend) needs only onnxruntime, tokenizers and numpy. No network access here.
"""
import bisect
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

LABELS = ("person", "street address", "email")
LABEL_TO_TYPE = {"person": "PERSON", "street address": "ADDRESS", "email": "EMAIL"}
MODEL_FILES = ("model_quantized.onnx", "model.onnx")


class NerUnavailable(RuntimeError):
    """The model is not installed. Scrubbing is blocked rather than silently running rules only."""


@dataclass(frozen=True)
class NerHit:
    start: int
    end: int
    label: str
    score: float


class Backend(Protocol):
    def predict(self, text: str, labels: tuple, threshold: float) -> list[NerHit]: ...


@dataclass
class NerConfig:
    model_dir: Path | None = None
    threshold: float = 0.5            # hits at or above this are scrubbed
    near_miss: float = 0.2            # hits within this distance below it become review flags
    idle_seconds: float = 600.0       # unload after this long without a call
    labels: tuple = LABELS


@dataclass
class NerResult:
    hits: list = field(default_factory=list)          # score >= threshold
    near_misses: list = field(default_factory=list)   # threshold - near_miss <= score < threshold


def find_model_file(model_dir: Path | None) -> Path | None:
    if model_dir:
        for name in MODEL_FILES:
            if (Path(model_dir) / name).is_file():
                return Path(model_dir) / name
    return None


class NerModel:
    def __init__(self, config: NerConfig | None = None, backend_factory: Callable[[], Backend] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config or NerConfig()
        self._factory = backend_factory
        self._clock = clock
        self._backend: Backend | None = None
        self._last_used = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def available(self) -> bool:
        return self._factory is not None or find_model_file(self.config.model_dir) is not None

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    def _load(self) -> Backend:
        if self._backend is None:
            if self._factory is not None:
                self._backend = self._factory()
            else:
                model = find_model_file(self.config.model_dir)
                if model is None:
                    raise NerUnavailable(f"No model found in {self.config.model_dir}. Run scripts/export_onnx.py.")
                self._backend = OnnxGlinerBackend(model.parent, model.name)
        return self._backend

    def detect(self, text: str) -> NerResult:
        """Run the model on one piece of text (a turn). Offsets are relative to text."""
        floor = max(0.0, self.config.threshold - self.config.near_miss)
        with self._lock:
            backend = self._load()
            self._last_used = self._clock()
            raw = backend.predict(text, self.config.labels, floor)
        res = NerResult()
        for h in raw:
            if h.score >= self.config.threshold:
                res.hits.append(h)
            elif h.score >= floor:
                res.near_misses.append(h)
        return res

    def unload_if_idle(self) -> bool:
        with self._lock:
            if self._backend is not None and self._clock() - self._last_used >= self.config.idle_seconds:
                self._backend = None
                return True
        return False

    def start_reaper(self, interval: float = 30.0) -> None:
        """Background thread that frees the model when idle. Call stop_reaper() on shutdown."""
        def run():
            while not self._stop.wait(interval):
                self.unload_if_idle()
        self._stop.clear()
        threading.Thread(target=run, daemon=True, name="ner-reaper").start()

    def stop_reaper(self) -> None:
        self._stop.set()


# --- real backend: GLiNER span model exported to ONNX, run with onnxruntime ------------------
_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")


class OnnxGlinerBackend:
    """Mirrors GLiNER's span-model preprocessing. Verified against the gliner library by
    scripts/check_onnx_parity.py; do not trust it on a new model export before running that."""

    def __init__(self, model_dir: Path, model_file: str, chunk_words: int = 200, overlap_words: int = 20):
        import numpy as np                        # imported here so the app starts without them
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self._np = np
        cfg_path = Path(model_dir) / "gliner_config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
        self.max_width = int(cfg.get("max_width", 12))
        self.ent = cfg.get("ent_token", "<<ENT>>")
        self.sep = cfg.get("sep_token", "<<SEP>>")
        self.chunk, self.overlap = chunk_words, overlap_words
        self.tok = Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
        self.session = ort.InferenceSession(str(Path(model_dir) / model_file), providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}

    def predict(self, text: str, labels: tuple, threshold: float) -> list[NerHit]:
        words = [(m.group(), m.start(), m.end()) for m in _WORD.finditer(text)]
        hits: list[NerHit] = []
        step = max(1, self.chunk - self.overlap)
        for lo in range(0, max(len(words), 1), step):
            chunk = words[lo:lo + self.chunk]
            if not chunk:
                break
            hits += self._run(chunk, labels, threshold)
            if lo + self.chunk >= len(words):
                break
        return self._flat(hits)

    def _run(self, chunk, labels, threshold) -> list[NerHit]:
        np = self._np
        prompt = []
        for label in labels:
            prompt += [self.ent, label]
        prompt.append(self.sep)
        enc = self.tok.encode(prompt + [w for w, _, _ in chunk], is_pretokenized=True)
        n, width, plen = len(chunk), self.max_width, len(prompt)
        mask, prev = [], None
        for wid in enc.word_ids:
            mask.append(0 if wid is None or wid == prev or wid < plen else wid - plen + 1)
            prev = wid
        span_idx = np.zeros((1, n * width, 2), dtype=np.int64)
        span_mask = np.zeros((1, n * width), dtype=bool)
        for i in range(n):
            for j in range(width):
                if i + j < n:
                    span_idx[0, i * width + j] = (i, i + j)
                    span_mask[0, i * width + j] = True
        feeds = {"input_ids": np.array([enc.ids], dtype=np.int64),
                 "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                 "words_mask": np.array([mask], dtype=np.int64),
                 "text_lengths": np.array([[n]], dtype=np.int64),
                 "span_idx": span_idx, "span_mask": span_mask}
        logits = self.session.run(None, {k: v for k, v in feeds.items() if k in self.input_names})[0]
        probs = 1.0 / (1.0 + np.exp(-logits))                    # [1, n, width, classes]
        out = []
        for i, j, c in zip(*np.where(probs[0] >= threshold)):
            if i + j < n:
                out.append(NerHit(chunk[i][1], chunk[i + j][2], labels[c], float(probs[0, i, j, c])))
        return out

    @staticmethod
    def _flat(hits: list[NerHit]) -> list[NerHit]:
        """Greedy non-overlapping selection by score, as GLiNER does for flat NER."""
        chosen: list[NerHit] = []          # kept sorted by start and never overlapping, so a bisect finds any clash
        starts: list[int] = []
        for h in sorted(hits, key=lambda h: -h.score):
            i = bisect.bisect_right(starts, h.start)
            if (i > 0 and chosen[i - 1].end > h.start) or (i < len(chosen) and chosen[i].start < h.end):
                continue
            chosen.insert(i, h)
            starts.insert(i, h.start)
        return chosen
