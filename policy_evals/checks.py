"""Deterministic checks on one agent response.

Each check returns a CheckResult with a message written for the person who
reads a failing CI log: what was expected, what came back, and why it matters.
Explanation quality is not graded here; that is the human review sheet's job.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agent.base import AgentResponse
from .cases import Case
from .policies import Corpus


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str

    def to_json(self) -> dict:
        return {"name": self.name, "passed": self.passed, "message": self.message}


def check_action(case: Case, r: AgentResponse) -> CheckResult:
    ok = r.action == case.expect.action
    return CheckResult(
        "action", ok,
        f"action is {r.action}" if ok
        else f"expected action {case.expect.action}, agent chose {r.action or 'nothing'}",
    )


def check_clause(case: Case, r: AgentResponse) -> CheckResult | None:
    if not case.expect.clause:
        return None
    cited = [c.clause for c in r.citations]
    ok = case.expect.clause in cited
    return CheckResult(
        "clause", ok,
        f"cites {case.expect.clause}" if ok
        else f"expected a citation of {case.expect.clause}, agent cited "
        + (", ".join(cited) if cited else "nothing"),
    )


def check_version(case: Case, r: AgentResponse, corpus: Corpus) -> CheckResult | None:
    if not case.expect.version:
        return None
    doc = case.expect.document
    of_doc = [c for c in r.citations if c.document == doc]
    target = [c for c in of_doc if c.clause == case.expect.clause] or of_doc
    if not target:
        return CheckResult("version", False,
                           f"expected a citation of {doc} v{case.expect.version}, agent cited no {doc} clause")
    bad = [c for c in target if c.version != case.expect.version]
    if bad:
        return CheckResult(
            "version", False,
            f"expected {doc} v{case.expect.version}, agent cited "
            + ", ".join(f"v{c.version} ({c.clause})" for c in bad),
        )
    return CheckResult("version", True, f"cites {doc} v{case.expect.version}")


def check_in_force(case: Case, r: AgentResponse, corpus: Corpus) -> CheckResult | None:
    """Every citation must point at a clause in force on the movement date,
    in a document that applies to the case's project.

    This check reads the current procedure documents, not the case label, so
    it catches a retired clause even before anyone updates the test labels.
    """
    if not r.citations:
        return None
    problems = []
    for c in r.citations:
        cited_version = corpus.get(c.document, c.version)
        if cited_version is None:
            problems.append(f"cited {c.label()}, but {c.document} has no version {c.version}")
            continue
        if c.clause not in cited_version.clauses:
            problems.append(f"cited {c.label()}, but that version has no clause {c.clause}")
            continue
        if case.project and cited_version.applies_to not in ("all", case.project):
            problems.append(f"cited {c.label()}, which applies to {cited_version.applies_to} "
                            f"stock, not {case.project}")
            continue
        if case.movement_day is None:
            continue
        current = corpus.version_in_force(c.document, case.movement_day)
        if current is None:
            problems.append(f"cited {c.label()}, but no {c.document} version is in force on {case.movement_date}")
        elif c.clause not in current.clauses:
            ret = corpus.retirement(c.document, c.clause)
            detail = ""
            if ret:
                detail = f" (retired from {ret.retired_from.isoformat()}" + (
                    f", replaced by {ret.replaced_by})" if ret.replaced_by else ")")
            problems.append(
                f"cited {c.label()}, but for a movement on {case.movement_date} the version in force "
                f"is {c.document} v{current.version}, where {c.clause} is retired{detail}"
            )
        elif current.version != c.version:
            problems.append(
                f"cited {c.label()}, a superseded version: for a movement on {case.movement_date} "
                f"the version in force is {c.document} v{current.version}"
            )
    if problems:
        return CheckResult("in_force", False, "; ".join(problems))
    return CheckResult("in_force", True, "every citation is in force on the movement date")


def check_pair(case: Case, r: AgentResponse, english: tuple[Case, AgentResponse] | None) -> CheckResult | None:
    """A French or Arabic question must reach the same decision as its English twin."""
    if not case.pair or case.language == "en" or english is None:
        return None
    _, er = english
    mine = (r.action, sorted(c.clause for c in r.citations))
    theirs = (er.action, sorted(c.clause for c in er.citations))
    if mine == theirs:
        return CheckResult("same_decision", True, f"same decision as the English question ({r.action})")
    return CheckResult(
        "same_decision", False,
        f"English question led to {theirs[0]} citing {', '.join(theirs[1]) or 'nothing'}; "
        f"this {case.language} question led to {mine[0] or 'nothing'} citing {', '.join(mine[1]) or 'nothing'}",
    )


def run_checks(case: Case, r: AgentResponse, corpus: Corpus,
               english: tuple[Case, AgentResponse] | None = None) -> list[CheckResult]:
    if r.error:
        return [CheckResult("agent_reply", False, f"agent did not give a usable reply: {r.error}")]
    results = [
        check_action(case, r),
        check_clause(case, r),
        check_version(case, r, corpus),
        check_in_force(case, r, corpus),
        check_pair(case, r, english),
    ]
    return [x for x in results if x is not None]
