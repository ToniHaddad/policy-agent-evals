"""The contract every agent under test meets.

Request (what the harness sends)::

    {"question": "...", "context": {"project": "FA-2026" | null,
     "warehouse": "WH-12", "movement_date": "2026-11-24" | null,
     "language": "en" | "fr" | "ar"}}

Response (what the agent returns)::

    {"answer": "...", "action": "answer" | "ask_clarification" | "escalate",
     "citations": [{"document": "fa-2026-annex", "version": "2.0", "clause": "FA-4.2"}]}

``escalate`` means the request goes to the operations manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

ACTIONS = ("answer", "ask_clarification", "escalate")


class ResponseFormatError(ValueError):
    """The agent replied, but not in the agreed shape."""


class AgentError(RuntimeError):
    """The agent could not be reached or failed to reply."""


@dataclass(frozen=True)
class Citation:
    document: str
    version: str
    clause: str

    def label(self) -> str:
        return f"{self.document} v{self.version} {self.clause}"


@dataclass(frozen=True)
class AgentRequest:
    question: str
    project: str | None
    warehouse: str | None
    movement_date: str | None
    language: str

    def to_json(self) -> dict:
        return {
            "question": self.question,
            "context": {
                "project": self.project,
                "warehouse": self.warehouse,
                "movement_date": self.movement_date,
                "language": self.language,
            },
        }

    @classmethod
    def from_json(cls, d: dict) -> "AgentRequest":
        try:
            ctx = d["context"]
            return cls(
                question=str(d["question"]),
                project=ctx.get("project"),
                warehouse=ctx.get("warehouse"),
                movement_date=ctx.get("movement_date"),
                language=str(ctx.get("language", "en")),
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ResponseFormatError(f"bad request: {exc}") from exc


@dataclass
class AgentResponse:
    answer: str
    action: str
    citations: list[Citation] = field(default_factory=list)
    error: str | None = None  # set by the harness when the agent failed

    def to_json(self) -> dict:
        d = {
            "answer": self.answer,
            "action": self.action,
            "citations": [
                {"document": c.document, "version": c.version, "clause": c.clause}
                for c in self.citations
            ],
        }
        if self.error:
            d["error"] = self.error
        return d

    @classmethod
    def from_json(cls, d: object) -> "AgentResponse":
        """Parse and validate an agent's JSON reply. Raises ResponseFormatError."""
        if not isinstance(d, dict):
            raise ResponseFormatError("response is not a JSON object")
        if d.get("error"):
            return cls(answer=str(d.get("answer", "")), action=str(d.get("action", "")),
                       citations=[], error=str(d["error"]))
        missing = [k for k in ("answer", "action", "citations") if k not in d]
        if missing:
            raise ResponseFormatError(f"response is missing {', '.join(missing)}")
        if d["action"] not in ACTIONS:
            raise ResponseFormatError(
                f"action '{d['action']}' is not one of {', '.join(ACTIONS)}"
            )
        if not isinstance(d["citations"], list):
            raise ResponseFormatError("citations must be a list")
        cites = []
        for i, c in enumerate(d["citations"]):
            if not isinstance(c, dict) or not all(
                k in c for k in ("document", "version", "clause")
            ):
                raise ResponseFormatError(
                    f"citation {i} needs document, version and clause"
                )
            cites.append(Citation(str(c["document"]), str(c["version"]), str(c["clause"])))
        return cls(answer=str(d["answer"]), action=d["action"], citations=cites)

    @classmethod
    def failed(cls, message: str) -> "AgentResponse":
        return cls(answer="", action="", citations=[], error=message)


class Agent(Protocol):
    name: str

    def describe(self) -> dict: ...

    def ask(self, request: AgentRequest) -> AgentResponse: ...
