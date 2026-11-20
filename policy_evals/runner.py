"""Run the suite LIVE against an agent, or REPLAY recorded transcripts.

LIVE asks the agent every question and records what it said. REPLAY reads a
recorded transcript file and re-checks it against the current cases and the
current policy corpus without any agent present. Both produce a RunResult;
its ``mode`` is fixed when it is created and every output names it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .agent.base import AgentError, AgentRequest, AgentResponse, ResponseFormatError
from .cases import Case, label_warnings
from .checks import CheckResult, run_checks
from .policies import Corpus

TRANSCRIPT_KIND = "policy-agent-evals/transcripts"
TRANSCRIPT_FORMAT = 1


class Mode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class TranscriptError(ValueError):
    pass


@dataclass
class CaseResult:
    case: Case
    response: AgentResponse
    checks: list[CheckResult]
    known_failure: str | None = None
    latency_ms: float | None = None

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def status(self) -> str:
        """pass, fail, known_fail, or unexpected_pass (a known failure that now passes)."""
        if self.known_failure is not None:
            return "unexpected_pass" if self.passed else "known_fail"
        return "pass" if self.passed else "fail"

    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


@dataclass
class RunResult:
    mode: Mode
    agent: dict
    started_at: str
    recorded_at: str
    corpus_fingerprint: str
    results: list[CaseResult]
    warnings: list[str] = field(default_factory=list)
    transcript_path: str = ""

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def gate_passed(self) -> bool:
        return self.count("fail") == 0 and self.count("unexpected_pass") == 0

    def breakdown(self) -> list[str]:
        """Pass counts by language and by tag, for the console and the README."""
        groups: dict[str, list[CaseResult]] = {}
        for r in self.results:
            groups.setdefault(f"language {r.case.language}", []).append(r)
            for t in r.case.tags:
                groups.setdefault(f"tag {t}", []).append(r)
        lines = []
        for name in sorted(groups):
            rs = groups[name]
            ok = sum(1 for r in rs if r.passed)
            lines.append(f"{name:<24} {ok:>2}/{len(rs):<2} pass")
        return lines

    def summary_line(self) -> str:
        return (
            f"{self.mode.value}: {len(self.results)} cases, {self.count('pass')} pass, "
            f"{self.count('fail')} fail, {self.count('known_fail')} known failures, "
            f"{self.count('unexpected_pass')} unexpected passes -> "
            + ("GATE PASSED" if self.gate_passed else "GATE FAILED")
        )

    def to_json(self) -> dict:
        return {
            "mode": self.mode.value,
            "agent": self.agent,
            "started_at": self.started_at,
            "transcripts_recorded_at": self.recorded_at,
            "corpus_fingerprint": self.corpus_fingerprint,
            "gate_passed": self.gate_passed,
            "warnings": self.warnings,
            "results": [
                {
                    "case": r.case.id,
                    "status": r.status,
                    "known_failure": r.known_failure,
                    "response": r.response.to_json(),
                    "checks": [c.to_json() for c in r.checks],
                }
                for r in self.results
            ],
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def evaluate(mode: Mode, responses: dict[str, AgentResponse], cases: list[Case],
             corpus: Corpus, known: dict[str, str], *, agent: dict, recorded_at: str,
             extra_failures: dict[str, CheckResult] | None = None,
             latencies: dict[str, float] | None = None) -> RunResult:
    extra_failures = extra_failures or {}
    english = {
        c.pair: (c, responses[c.id])
        for c in cases if c.pair and c.language == "en" and c.id in responses
    }
    results = []
    for case in cases:
        if case.id in extra_failures:
            checks = [extra_failures[case.id]]
            resp = responses.get(case.id) or AgentResponse.failed(extra_failures[case.id].message)
        else:
            resp = responses[case.id]
            checks = run_checks(case, resp, corpus, english.get(case.pair))
        results.append(CaseResult(case, resp, checks, known.get(case.id),
                                  (latencies or {}).get(case.id)))
    return RunResult(
        mode=mode, agent=agent, started_at=_now(), recorded_at=recorded_at,
        corpus_fingerprint=corpus.fingerprint, results=results,
        warnings=label_warnings(cases, corpus),
    )


def run_live(agent, cases: list[Case], corpus: Corpus, known: dict[str, str]) -> tuple[RunResult, dict]:
    """Ask the agent every question. Returns the result and the transcript to save."""
    started = _now()
    responses: dict[str, AgentResponse] = {}
    latencies: dict[str, float] = {}
    entries = []
    for case in cases:
        req = case.request()
        t0 = time.perf_counter()
        try:
            resp = agent.ask(req)
        except (AgentError, ResponseFormatError) as exc:
            resp = AgentResponse.failed(str(exc))
        latencies[case.id] = round((time.perf_counter() - t0) * 1000, 2)
        responses[case.id] = resp
        entries.append({"case": case.id, "request": req.to_json(), "response": resp.to_json()})
    transcript = {
        "kind": TRANSCRIPT_KIND,
        "format": TRANSCRIPT_FORMAT,
        "recorded_at": started,
        "agent": agent.describe(),
        "entries": entries,
    }
    result = evaluate(Mode.LIVE, responses, cases, corpus, known,
                      agent=agent.describe(), recorded_at=started, latencies=latencies)
    result.started_at = started
    return result, transcript


def save_transcript(transcript: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(transcript, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_transcript(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise TranscriptError(f"no transcript at {p}. Record one with: evals run")
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("kind") != TRANSCRIPT_KIND:
        raise TranscriptError(f"{p} is not a transcript file (kind={data.get('kind')!r})")
    if data.get("format") != TRANSCRIPT_FORMAT:
        raise TranscriptError(f"{p} has transcript format {data.get('format')}, expected {TRANSCRIPT_FORMAT}")
    return data


def replay(transcript: dict, cases: list[Case], corpus: Corpus, known: dict[str, str],
           transcript_path: str = "") -> RunResult:
    """Re-check recorded responses. No agent is called."""
    by_case = {e["case"]: e for e in transcript["entries"]}
    responses: dict[str, AgentResponse] = {}
    extra: dict[str, CheckResult] = {}
    for case in cases:
        entry = by_case.get(case.id)
        if entry is None:
            extra[case.id] = CheckResult("transcript", False,
                                         "no recorded reply for this case; re-record with: evals run")
            continue
        if entry["request"] != case.request().to_json():
            extra[case.id] = CheckResult(
                "transcript", False,
                "the recorded reply was for a different question or context than the case "
                "now has; re-record with: evals run")
            continue
        try:
            responses[case.id] = AgentResponse.from_json(entry["response"])
        except ResponseFormatError as exc:
            responses[case.id] = AgentResponse.failed(str(exc))
    agent = dict(transcript.get("agent", {}))
    result = evaluate(Mode.REPLAY, responses, cases, corpus, known, agent=agent,
                      recorded_at=transcript.get("recorded_at", "unknown"), extra_failures=extra)
    result.transcript_path = transcript_path
    return result
