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
    clause: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class Case:
    id: str
    office: str
    travel_date: str | None
    language: str
    question: str
    expect: Expectation
    pair: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def request(self) -> AgentRequest:
        return AgentRequest(self.question, self.office, self.travel_date, self.language)

    @property
    def travel_day(self) -> date | None:
        return date.fromisoformat(self.travel_date) if self.travel_date else None


def _case_from(raw: dict, where: str) -> Case:
    for key in ("id", "office", "language", "question", "expect"):
        if key not in raw:
            raise CaseFormatError(f"{where}: missing '{key}'")
    exp = raw["expect"]
    if exp.get("action") not in ACTIONS:
        raise CaseFormatError(f"{raw['id']}: expect.action must be one of {ACTIONS}")
    if exp["action"] != "ask_clarification" and not (exp.get("clause") and exp.get("version")):
        raise CaseFormatError(f"{raw['id']}: answer and escalate cases need clause and version")
    if raw["language"] not in LANGUAGES:
        raise CaseFormatError(f"{raw['id']}: language must be one of {LANGUAGES}")
    td = raw.get("travel_date")
    if isinstance(td, date):
        td = td.isoformat()
    elif td is not None:
        date.fromisoformat(str(td))
        td = str(td)
    return Case(
        id=str(raw["id"]),
        office=str(raw["office"]),
        travel_date=td,
        language=raw["language"],
        question=str(raw["question"]).strip(),
        expect=Expectation(
            exp["action"],
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
    """Case labels that no longer match the policy corpus.

    A policy owner who retires a clause also makes some hand labels stale. The
    run still checks the agent against the corpus, but these warnings tell the
    owner which labels to update.
    """
    out = []
    for c in cases:
        if not c.expect.clause or not c.travel_day:
            continue
        doc = corpus.document_for_office(c.office)
        v = corpus.version_in_force(doc, c.travel_day) if doc else None
        if v is None:
            out.append(f"{c.id}: no {c.office} policy in force on {c.travel_date}")
        elif v.version != c.expect.version or c.expect.clause not in v.clauses:
            out.append(
                f"{c.id}: label expects {c.expect.clause} v{c.expect.version}, but on "
                f"{c.travel_date} {doc} v{v.version} is in force"
                + ("" if c.expect.clause in v.clauses else f" and has no {c.expect.clause}")
            )
    return out
