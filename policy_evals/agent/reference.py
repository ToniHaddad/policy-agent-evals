"""The reference agent: the system under test.

It stands in for a deployed procedures assistant that warehouse keepers ask
from their phones. Like a real one, it does not read the procedure folder
live: it answers from a knowledge snapshot taken when it was last
"published" (``evals snapshot``). If a policy owner publishes a new version
and nobody refreshes the snapshot, the agent keeps citing what it knew. That
is the failure this repo exists to catch.

How it answers, in order:
1. No known project or no movement date: ask, because the documents and the
   version in force depend on them.
2. Use the general Warehouse Procedure plus the project's annex, each in the
   version in force on the movement date (from its snapshot).
3. Read facts from the question with English patterns: pieces (and
   "12 boxes + 6 pieces ... 24 per box"), days to expiry, "expired", damage,
   transfer, partner, donation.
4. Expired stock: escalate (it may never be dispatched).
5. Damage: ask for the number of pieces if missing, else escalate the
   write-off to the operations manager, naming who else must sign.
6. Transfer to another project: answer "no" where the annex forbids it,
   otherwise escalate (the operations manager creates transfers).
7. Partner dispatch and donations: answer from the annex clause.
8. Days to expiry given: escalate inside the annex's window, else answer.
   A question about specific stock near expiry with no date: ask.
9. Otherwise BM25 over the clauses in force; answer with the top clause, or
   ask the user to rephrase if nothing matches.
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
BOXES = re.compile(rf"\b{_NUM}\s+boxes?\b(?:\s*(?:\+|and)\s*{_NUM}\s+pieces?)?")
PER_BOX = re.compile(r"\b(\d+)\s*(?:per|a|/)\s*box\b")
PIECES = re.compile(rf"\b{_NUM}\s+(?:damaged\s+)?pieces?\b")
EXPIRY_DAYS = re.compile(rf"\bexpires?\s+in\s+{_NUM}\s+days?\b|\b{_NUM}\s+days?\s+(?:before|to|until|from)\s+expiry\b")
EXPIRED = re.compile(r"\b(has|have|had|already|is|are)?\s*expired\b")
DAMAGE = re.compile(r"\b(damaged|crushed|broken|spoiled|torn|leaking|flood\w*|got wet|water damage)\b")
TRANSFER = re.compile(r"\btransfer\w*\b.*\bproject\b|\bproject\b.*\btransfer\w*\b")
PARTNER = re.compile(r"\bpartner\b")
DONATION = re.compile(r"\bdonat\w*|\bdonor\b")
EXPIRY = re.compile(r"\bexpir\w*")
NEAR_EXPIRY_PERSONAL = re.compile(r"\b(still|too close|close to)\b")

WRITE_OFF_LIMIT = re.compile(r"up to (\d+) pieces")
CO_SIGNER = re.compile(r"Above (\d+) pieces the ([a-zA-Z0-9\- ]+?) must also sign")
INFORMED = re.compile(r"Above (\d+) pieces the ([a-zA-Z ]+?) is informed")
EXPIRY_WINDOW = re.compile(r"within (\d+) days of its expiry date")
FORBIDS_TRANSFER = re.compile(r"may not be transferred")

MIN_SCORE = 1.0


def _num(tok: str | None) -> int | None:
    if tok is None:
        return None
    return int(tok) if tok.isdigit() else NUMBER_WORDS[tok]


@dataclass
class Facts:
    pieces: int | None
    boxes_without_size: bool
    expiry_days: int | None
    expired: bool
    damage: bool
    transfer: bool
    partner: bool
    donation: bool
    expiry_topic: bool
    near_expiry_personal: bool


def read_facts(question: str) -> Facts:
    q = fold(question)
    pieces, boxes_without_size = None, False
    b = BOXES.search(q)
    if b:
        per = PER_BOX.search(q)
        if per:
            pieces = _num(b.group(1)) * int(per.group(1)) + (_num(b.group(2)) or 0)
        else:
            boxes_without_size = True
    else:
        p = PIECES.search(q)
        if p:
            pieces = _num(p.group(1))
    e = EXPIRY_DAYS.search(q)
    expiry_days = _num(e.group(1) or e.group(2)) if e else None
    return Facts(
        pieces=pieces,
        boxes_without_size=boxes_without_size,
        expiry_days=expiry_days,
        expired=bool(EXPIRED.search(q)),
        damage=bool(DAMAGE.search(q)),
        transfer=bool(TRANSFER.search(q)),
        partner=bool(PARTNER.search(q)),
        donation=bool(DONATION.search(q)),
        expiry_topic=bool(EXPIRY.search(q)),
        near_expiry_personal=bool(NEAR_EXPIRY_PERSONAL.search(q)),
    )


class ReferenceAgent:
    name = "reference-bm25"

    def __init__(self, knowledge: Corpus, snapshot_id: str = ""):
        self.knowledge = knowledge
        self.snapshot_id = snapshot_id or knowledge.fingerprint
        self._indexes: dict[tuple, BM25] = {}

    @classmethod
    def from_snapshot(cls, path: str | Path = DEFAULT_SNAPSHOT) -> "ReferenceAgent":
        data = json.loads(Path(path).read_bytes())
        return cls(Corpus.from_snapshot(data), data.get("corpus_fingerprint", ""))

    def describe(self) -> dict:
        return {
            "name": self.name,
            "kind": "in-process",
            "knowledge_snapshot": self.snapshot_id,
            "versions_known": [f"{v.document} v{v.version}" for v in self.knowledge.versions],
        }

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _cite(v: PolicyVersion, c: Clause) -> Citation:
        return Citation(v.document, v.version, c.id)

    @staticmethod
    def _ask(text: str) -> AgentResponse:
        return AgentResponse(answer=text, action="ask_clarification", citations=[])

    @staticmethod
    def _by_title(versions: list[PolicyVersion], word: str) -> tuple[PolicyVersion, Clause] | None:
        for v in versions:
            for c in v.clauses.values():
                if word.lower() in c.title.lower():
                    return v, c
        return None

    def _search(self, versions: list[PolicyVersion], question: str):
        key = tuple((v.document, v.version) for v in versions)
        pairs = [(v, c) for v in versions for c in v.clauses.values()]
        if key not in self._indexes:
            self._indexes[key] = BM25([f"{c.title} {c.title} {c.text}" for _, c in pairs])
        scores = self._indexes[key].scores(question)
        best = max(range(len(pairs)), key=lambda i: scores[i])
        return pairs[best][0], pairs[best][1], scores[best]

    def _answer(self, v: PolicyVersion, c: Clause, lead: str = "") -> AgentResponse:
        return AgentResponse(answer=f"{lead}{c.title} ({c.id}): {c.text}", action="answer",
                             citations=[self._cite(v, c)])

    # -- the agent ---------------------------------------------------------
    def ask(self, request: AgentRequest) -> AgentResponse:
        docs = self.knowledge.documents_for_project(request.project or "")
        if not docs:
            projects = ", ".join(self.knowledge.projects())
            return self._ask(f"Which project funds this stock? The rules differ by project ({projects}).")
        if not request.movement_date:
            return self._ask(
                "What is the date of the movement? The procedure version that applies "
                "depends on it."
            )
        day = date.fromisoformat(request.movement_date)
        versions = [v for v in (self.knowledge.version_in_force(d, day) for d in docs) if v]
        if not versions:
            return self._ask("No procedure is in force for that date. Please check the date.")
        annex = [v for v in versions if v.applies_to != "all"]
        general = [v for v in versions if v.applies_to == "all"]
        f = read_facts(request.question)

        if f.expired:
            found = self._by_title(general, "Expired stock")
            if found:
                v, c = found
                return AgentResponse(
                    answer=f"No. Expired stock must never be dispatched ({c.id}). Move it to "
                    "quarantine and record it on a damage report; the operations manager "
                    "approves the write-off and disposal.",
                    action="escalate", citations=[self._cite(v, c)])

        if f.damage:
            if f.boxes_without_size:
                return self._ask("How many pieces are in each box? Write-offs are recorded in pieces.")
            if f.pieces is None:
                return self._ask("How many pieces were damaged? The approval needed depends on the quantity.")
            rule = self._by_title(annex, "Write-off")
            report = self._by_title(general, "Damage report")
            cites, extra = [], ""
            if rule:
                v, c = rule
                cites.append(self._cite(v, c))
                co, inf = CO_SIGNER.search(c.text), INFORMED.search(c.text)
                if co and f.pieces > int(co.group(1)):
                    extra = f" {f.pieces} pieces is above {co.group(1)}, so the {co.group(2)} must also sign ({c.id})."
                elif co:
                    extra = f" {f.pieces} pieces is within the operations manager's limit of {co.group(1)} ({c.id})."
                elif inf and f.pieces > int(inf.group(1)):
                    extra = f" Above {inf.group(1)} pieces the {inf.group(2)} is informed ({c.id})."
            if report:
                cites.append(self._cite(*report))
            return AgentResponse(
                answer="Do not remove the stock yet. Record a damage report with a written "
                f"description of the incident; it becomes a write-off only when the operations "
                f"manager approves it.{extra}",
                action="escalate", citations=cites)

        if f.transfer:
            rule = self._by_title(annex, "Transfers")
            if rule:
                v, c = rule
                if FORBIDS_TRANSFER.search(c.text):
                    return self._answer(v, c, "No. ")
                return AgentResponse(
                    answer=f"Only the operations manager can create this transfer. {c.text} ({c.id})",
                    action="escalate", citations=[self._cite(v, c)])

        if f.partner:
            rule = self._by_title(annex, "Dispatch destinations")
            if rule:
                return self._answer(*rule)

        if f.donation:
            rule = self._by_title(annex, "donation")
            if rule:
                return self._answer(*rule)

        if f.expiry_topic:
            rule = self._by_title(annex, "Near-expiry")
            window = EXPIRY_WINDOW.search(rule[1].text) if rule else None
            if f.expiry_days is not None and window:
                v, c = rule
                limit = int(window.group(1))
                if f.expiry_days < limit:
                    return AgentResponse(
                        answer=f"Yes. {f.expiry_days} days is inside the {limit}-day window in {c.id}: "
                        "release it for distribution or report it to the operations manager now.",
                        action="escalate", citations=[self._cite(v, c)])
                return AgentResponse(
                    answer=f"Not yet. {f.expiry_days} days is outside the {limit}-day window in {c.id}. "
                    "Keep issuing the earliest expiry first.",
                    action="answer", citations=[self._cite(v, c)])
            if f.expiry_days is None and f.near_expiry_personal:
                return self._ask("What is the expiry date on the batch? The answer depends on how many days are left.")

        v, c, score = self._search(versions, request.question)
        if score < MIN_SCORE:
            return self._ask(
                "I could not find a procedure clause that matches your question. "
                "Could you rephrase it?"
            )
        return self._answer(v, c)


def write_snapshot(corpus: Corpus, path: str | Path = DEFAULT_SNAPSHOT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corpus.to_snapshot(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def snapshot_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
