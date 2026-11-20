"""The reference agent: the system under test.

It stands in for a deployed policy assistant. Like a real one, it does not
read the policy folder live: it answers from a knowledge snapshot taken when
it was last "published" (``evals snapshot``). If a policy owner publishes a
new version and nobody refreshes the snapshot, the agent keeps citing what it
knew. That is the failure this repo exists to catch.

How it answers, in order:
1. No office or no travel date: ask, because the version in force depends on it.
2. Pick the version in force on the travel date from its snapshot.
3. Read facts from the question with English patterns: days until departure,
   a nightly hotel rate, "above the limit", "my hotel", "too late".
4. A personal question missing the deciding number: ask for it.
5. A rule broken (too few days, rate above the ceiling): escalate to the
   travel coordinator, citing the broken rule and the exceptions clause.
6. A number given and within the rule: answer, citing that rule.
7. Otherwise BM25 over the clauses of that version; answer with the top clause,
   or ask the user to rephrase if nothing matches.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..policies import Clause, Corpus, PolicyVersion
from .base import AgentRequest, AgentResponse, Citation
from .bm25 import BM25, fold

DEFAULT_SNAPSHOT = Path("agent_knowledge/snapshot.json")

NUMBER_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
_NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"
DAYS = re.compile(rf"\b{_NUM}\s+(?:calendar\s+|working\s+)?days?\b")
RATE = re.compile(r"(?:usd|us\$|\$)\s*(\d+)|(\d+)\s*(?:usd|us dollars|dollars|\$)")
OVER_LIMIT = re.compile(
    r"\b(above|over|exceed\w*|more than|higher than)\s+(the\s+)?"
    r"(usual\s+|normal\s+|hotel\s+|allowed\s+)?(limit|ceiling|maximum|cap|rate)\b"
)
OWN_HOTEL = re.compile(r"\b(my|our) hotel\b|\bthe hotel i\b")
TIMING = re.compile(r"\b(too late|enough notice|in time|left it late)\b")

ADVANCE_RULE = re.compile(r"at least (\d+) calendar days before departure")
CEILING_RULE = re.compile(r"may not exceed USD (\d+) per night")
APPROVER = re.compile(r"exception approved by the ([A-Z][a-z]+(?: (?:of )?[A-Z][a-z]+)*)")

MIN_SCORE = 1.0


@dataclass
class Facts:
    days: int | None
    rate: int | None
    over_limit: bool
    own_hotel: bool
    timing: bool


def read_facts(question: str) -> Facts:
    q = fold(question)
    days = None
    m = DAYS.search(q)
    if m:
        tok = m.group(1)
        days = int(tok) if tok.isdigit() else NUMBER_WORDS[tok]
    rate = None
    r = RATE.search(q)
    if r:
        rate = int(r.group(1) or r.group(2))
    return Facts(
        days=days,
        rate=rate,
        over_limit=bool(OVER_LIMIT.search(q)),
        own_hotel=bool(OWN_HOTEL.search(q)),
        timing=bool(TIMING.search(q)),
    )


def _find(version: PolicyVersion, pattern: re.Pattern) -> tuple[Clause, re.Match] | None:
    for c in version.clauses.values():
        m = pattern.search(c.text)
        if m:
            return c, m
    return None


class ReferenceAgent:
    name = "reference-bm25"

    def __init__(self, knowledge: Corpus, snapshot_id: str = ""):
        self.knowledge = knowledge
        self.snapshot_id = snapshot_id or knowledge.fingerprint
        self._indexes: dict[tuple[str, str], BM25] = {}

    @classmethod
    def from_snapshot(cls, path: str | Path = DEFAULT_SNAPSHOT) -> "ReferenceAgent":
        raw = Path(path).read_bytes()
        data = json.loads(raw)
        return cls(Corpus.from_snapshot(data), data.get("corpus_fingerprint", ""))

    def describe(self) -> dict:
        return {
            "name": self.name,
            "kind": "in-process",
            "knowledge_snapshot": self.snapshot_id,
            "versions_known": [f"{v.document} v{v.version}" for v in self.knowledge.versions],
        }

    # -- helpers -----------------------------------------------------------
    def _cite(self, v: PolicyVersion, c: Clause) -> Citation:
        return Citation(v.document, v.version, c.id)

    def _ask(self, text: str) -> AgentResponse:
        return AgentResponse(answer=text, action="ask_clarification", citations=[])

    def _search(self, v: PolicyVersion, question: str) -> tuple[Clause, float] | None:
        key = (v.document, v.version)
        clauses = list(v.clauses.values())
        if key not in self._indexes:
            self._indexes[key] = BM25([f"{c.title} {c.title} {c.text}" for c in clauses])
        scores = self._indexes[key].scores(question)
        best = max(range(len(clauses)), key=lambda i: scores[i])
        return clauses[best], scores[best]

    # -- the agent ---------------------------------------------------------
    def ask(self, request: AgentRequest) -> AgentResponse:
        doc = self.knowledge.document_for_office(request.office)
        if doc is None:
            offices = ", ".join(self.knowledge.offices())
            return self._ask(f"Which office do you travel for? I hold policies for: {offices}.")
        if not request.travel_date:
            return self._ask(
                "What date does your trip start? The rule that applies depends on "
                "the policy version in force on your travel date."
            )
        v = self.knowledge.version_in_force(doc, date.fromisoformat(request.travel_date))
        if v is None:
            return self._ask("I have no travel policy in force for that date. Please check the date.")

        facts = read_facts(request.question)
        advance = _find(v, ADVANCE_RULE)
        ceiling = _find(v, CEILING_RULE)
        exception = next((c for c in v.clauses.values() if "exception approved by" in c.text), None)

        if facts.own_hotel and facts.rate is None and not facts.over_limit:
            return self._ask("What is the nightly rate of the hotel, in USD? The answer depends on it.")
        if facts.timing and facts.days is None:
            return self._ask("How many days before departure are you submitting the travel request?")

        broken: list[tuple[Clause, str]] = []
        if facts.days is not None and advance:
            need = int(advance[1].group(1))
            if facts.days < need:
                broken.append((advance[0], f"{facts.days} days is less than the {need}-day minimum"))
        if ceiling and (facts.over_limit or (facts.rate is not None and facts.rate > int(ceiling[1].group(1)))):
            limit = ceiling[1].group(1)
            what = f"USD {facts.rate}" if facts.rate is not None else "Your hotel rate"
            broken.append((ceiling[0], f"{what} is above the USD {limit} per night ceiling"))

        if broken:
            cites = [self._cite(v, c) for c, _ in broken]
            approver = "the approver named in the policy"
            if exception:
                cites.append(self._cite(v, exception))
                m = APPROVER.search(exception.text)
                if m:
                    approver = "the " + m.group(1).strip()
            reasons = "; ".join(f"{why} ({c.id})" for c, why in broken)
            answer = (
                f"This needs an exception: {reasons}. Do not book yet. Send an exception "
                f"request to the travel coordinator, who passes it to {approver} for approval"
                + (f" ({exception.id})." if exception else ".")
            )
            return AgentResponse(answer=answer, action="escalate", citations=cites)

        if facts.days is not None and advance:
            need = int(advance[1].group(1))
            return AgentResponse(
                answer=f"Yes. {facts.days} days meets the {need}-day minimum in {advance[0].id}. "
                "Submit the travel request as usual.",
                action="answer",
                citations=[self._cite(v, advance[0])],
            )
        if facts.rate is not None and ceiling:
            limit = ceiling[1].group(1)
            return AgentResponse(
                answer=f"Yes. USD {facts.rate} per night is within the USD {limit} ceiling in {ceiling[0].id}.",
                action="answer",
                citations=[self._cite(v, ceiling[0])],
            )

        clause, score = self._search(v, request.question)
        if score < MIN_SCORE:
            return self._ask(
                "I could not find a clause in the travel policy that matches your question. "
                "Could you rephrase it?"
            )
        return AgentResponse(
            answer=f"{clause.title} ({clause.id}): {clause.text}",
            action="answer",
            citations=[self._cite(v, clause)],
        )


def write_snapshot(corpus: Corpus, path: str | Path = DEFAULT_SNAPSHOT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corpus.to_snapshot(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def snapshot_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
