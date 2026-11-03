"""The span type every detector emits. Offsets always refer to the original text."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str       # PERSON, EMAIL, ADDRESS, ...
    source: str     # speaker, registry, regex, cue, ...
    value: str      # text to register (as it appears in the input)

    @property
    def length(self) -> int:
        return self.end - self.start
