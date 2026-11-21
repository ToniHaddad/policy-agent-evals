"""Hand-labelled test cases, loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .agent.base import ACTIONS, AgentRequest
from .policies import Corpus

LANGUAGES = ("en", "fr", "ar")


class CaseFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Expectation:
    action: str
    document: str | None = None
    clause: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class Case:
    id: str
    project: str | None
    warehouse: str | None
    movement_date: str | None
    language: str
    question: str
    expect: Expectation
    pair: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def request(self) -> AgentRequest:
        return AgentRequest(self.question, self.project, self.warehouse,
                            self.movement_date, self.language)

    @property
    def movement_day(self) -> date | None:
        return date.fromisoformat(self.movement_date) if self.movement_date else None

    def context_label(self) -> str:
        return (f"{self.project or 'no project'}, {self.warehouse or 'no warehouse'}, "
                f"moved {self.movement_date or 'no date'}, {self.language}")


def _case_from(raw: dict, where: str) -> Case:
    for key in ("id", "language", "question", "expect"):
        if key not in raw:
            raise CaseFormatError(f"{where}: missing '{key}'")
    exp = raw["expect"]
    if exp.get("action") not in ACTIONS:
        raise CaseFormatError(f"{raw['id']}: expect.action must be one of {ACTIONS}")
    if exp["action"] != "ask_clarification" and not (
        exp.get("document") and exp.get("clause") and exp.get("version")
    ):
        raise CaseFormatError(f"{raw['id']}: answer and escalate cases need document, clause and version")
    if raw["language"] not in LANGUAGES:
        raise CaseFormatError(f"{raw['id']}: language must be one of {LANGUAGES}")
    md = raw.get("movement_date")
    if isinstance(md, date):
        md = md.isoformat()
    elif md is not None:
        date.fromisoformat(str(md))
        md = str(md)
    return Case(
        id=str(raw["id"]),
        project=raw.get("project"),
        warehouse=raw.get("warehouse"),
        movement_date=md,
        language=raw["language"],
        question=str(raw["question"]).strip(),
        expect=Expectation(
            exp["action"],
            exp.get("document"),
            exp.get("clause"),
            str(exp["version"]) if exp.get("version") is not None else None,
        ),
        pair=raw.get("pair"),
        tags=tuple(raw.get("tags") or ()),
    )


def load_cases(path: str | Path) -> list[Case]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CaseFormatError(f"{path}: expected a list of cases")
    cases = [_case_from(raw, f"{path}[{i}]") for i, raw in enumerate(data)]
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CaseFormatError(f"duplicate case ids: {', '.join(sorted(dupes))}")
    for pair in {c.pair for c in cases if c.pair}:
        langs = [c.language for c in cases if c.pair == pair]
        if "en" not in langs or len(langs) < 2:
            raise CaseFormatError(f"pair '{pair}' needs an English case and at least one other")
    return cases


def load_known_failures(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return {str(d["id"]): str(d.get("reason", "")) for d in data}


def label_warnings(cases: list[Case], corpus: Corpus) -> list[str]:
    """Case labels that no longer match the procedure documents.

    A policy owner who retires a clause also makes some hand labels stale. The
    run still checks the agent against the documents, but these warnings tell
    the owner which labels to update.
    """
    out = []
    for c in cases:
        e = c.expect
        if not e.clause or not c.movement_day:
            continue
        v = corpus.version_in_force(e.document, c.movement_day)
        if v is None:
            out.append(f"{c.id}: no version of {e.document} is in force on {c.movement_date}")
        elif v.version != e.version or e.clause not in v.clauses:
            out.append(
                f"{c.id}: label expects {e.clause} v{e.version}, but on "
                f"{c.movement_date} {e.document} v{v.version} is in force"
                + ("" if e.clause in v.clauses else f" and has no {e.clause}")
            )
    return out
