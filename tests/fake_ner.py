"""A stand-in for the GLiNER backend. Finds fixed strings with fixed scores."""
import re

from app.scrub.ner import NerHit


class FakeBackend:
    def __init__(self, table):
        self.table = table              # {"Kevin": ("person", 0.93)}
        self.calls = []

    def predict(self, text, labels, threshold):
        self.calls.append((text, threshold))
        hits = []
        for needle, (label, score) in self.table.items():
            for m in re.finditer(rf"(?<!\w){re.escape(needle)}(?!\w)", text):
                if score >= threshold:
                    hits.append(NerHit(m.start(), m.end(), label, score))
        return hits
