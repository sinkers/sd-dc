"""Reads loop_params.json, and refuses to answer for what is not yet known.

The design decision worth stating: a parameter whose value is null raises
`PendingReference` rather than returning a default. A default would be a number
nobody chose, indistinguishable downstream from one somebody did, and the
temperature basis of this whole model is currently null pending RD110. Making
that loud is the difference between a model that is honestly incomplete and one
that is quietly wrong.

`Param` carries the value together with its source and confidence grade, so a
result can be traced back without opening the JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PARAMS_PATH = Path(__file__).with_name("loop_params.json")

# Confidence grades, as used by cfd-cabinet-cooling/FINDINGS-AU01.md.
GRADES = {
    "H": "from a primary document",
    "M": "derived from one, assumptions stated",
    "C": "carried forward from a superseded source",
    "L": "engineering judgement or a placeholder",
}


class PendingReference(LookupError):
    """A parameter that has not been settled yet was asked for.

    Carries what would settle it, so the message is actionable rather than
    just an absence.
    """

    def __init__(self, path: str, pending: str, note: str = ""):
        self.path = path
        self.pending = pending
        msg = f"{path} is not yet known - pending {pending}"
        if note:
            msg += f"\n  {note}"
        super().__init__(msg)


@dataclass(frozen=True)
class Param:
    path: str
    value: Any
    unit: str = ""
    confidence: str = ""
    source: str = ""
    note: str = ""

    def __post_init__(self):
        if self.confidence and self.confidence not in GRADES:
            raise ValueError(f"{self.path}: unknown confidence grade {self.confidence!r}")

    def __float__(self) -> float:
        return float(self.value)

    def describe(self) -> str:
        bits = [f"{self.path} = {self.value}"]
        if self.unit:
            bits.append(self.unit)
        if self.confidence:
            bits.append(f"[{self.confidence}: {GRADES[self.confidence]}]")
        if self.source:
            bits.append(f"- {self.source}")
        return " ".join(bits)


def _flatten_note(raw) -> str:
    """Notes are written as a list of lines in the JSON, for readability there."""
    if isinstance(raw, list):
        return " ".join(raw)
    return raw or ""


class LoopParams:
    """The spec sheet. Dotted paths address it: `p.get("loads.rack_liquid_kw")`."""

    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: Path | str = PARAMS_PATH) -> "LoopParams":
        with open(path) as fh:
            return cls(json.load(fh))

    def _node(self, path: str) -> dict:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"no parameter at {path!r} (stopped at {part!r})")
            node = node[part]
        if not isinstance(node, dict) or "value" not in node:
            raise KeyError(f"{path!r} is a group, not a parameter")
        return node

    def param(self, path: str) -> Param:
        """The parameter with its provenance. Raises if it is still pending."""
        node = self._node(path)
        note = _flatten_note(node.get("note"))
        if node["value"] is None:
            raise PendingReference(path, node.get("pending", "an unrecorded source"), note)
        return Param(
            path=path,
            value=node["value"],
            unit=node.get("unit", ""),
            confidence=node.get("confidence", ""),
            source=node.get("source", ""),
            note=note,
        )

    def get(self, path: str) -> Any:
        """Just the value. Raises PendingReference if it is not settled."""
        return self.param(path).value

    def is_pending(self, path: str) -> bool:
        return self._node(path)["value"] is None

    def pending(self) -> list[tuple[str, str]]:
        """Every unsettled parameter as (path, what would settle it).

        This is the model's to-do list, and `dtloop status` prints it.
        """
        out: list[tuple[str, str]] = []

        def walk(node: Any, prefix: str) -> None:
            if not isinstance(node, dict):
                return
            if "value" in node:
                if node["value"] is None:
                    out.append((prefix, node.get("pending", "an unrecorded source")))
                return
            for key, child in node.items():
                if key.startswith("_"):
                    continue
                walk(child, f"{prefix}.{key}" if prefix else key)

        walk(self._data, "")
        return out

    def by_confidence(self, grade: str) -> list[Param]:
        """Every settled parameter at one confidence grade. `by_confidence("L")`
        is the list of numbers that are judgement rather than evidence."""
        if grade not in GRADES:
            raise ValueError(f"unknown confidence grade {grade!r}")
        found: list[Param] = []

        def walk(node: Any, prefix: str) -> None:
            if not isinstance(node, dict):
                return
            if "value" in node:
                if node["value"] is not None and node.get("confidence") == grade:
                    found.append(self.param(prefix))
                return
            for key, child in node.items():
                if key.startswith("_"):
                    continue
                walk(child, f"{prefix}.{key}" if prefix else key)

        walk(self._data, "")
        return found
