"""Command line: evals run | replay | snapshot | serve | serve-agent."""

from __future__ import annotations

import argparse
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from .agent.http import HttpAgent
from .agent.reference import DEFAULT_SNAPSHOT, ReferenceAgent, write_snapshot
from .agent.stub_server import DEFAULT_PORT, ExclusiveServer, make_server
from .cases import load_cases, load_known_failures
from .policies import Corpus
from .report import write_outputs
from .runner import Mode, RunResult, TranscriptError, load_transcript, replay, run_live, save_transcript

DEFAULT_TRANSCRIPT = "transcripts/reference-agent.json"


def _print_run(run: RunResult, paths: dict) -> None:
    rule = "=" * 72
    print(rule)
    if run.mode is Mode.LIVE:
        print(f"LIVE RUN  agent={run.agent.get('name')}  started={run.started_at}")
    else:
        print(f"REPLAY  no agent called  replies recorded={run.recorded_at}  by={run.agent.get('name')}")
    print(rule)
    for r in run.results:
        if r.status in ("fail", "unexpected_pass"):
            print(f"\n{r.status.upper()}  {r.case.id}  ({r.case.context_label()})")
            print(f"  question: {r.case.question}")
            print(f"  reply:    {r.response.action} {[c.label() for c in r.response.citations]}")
            for k in r.failed_checks():
                print(f"  {k.name}: {k.message}")
    if run.warnings:
        print(f"\n{len(run.warnings)} case label(s) no longer match the procedures:")
        for w in run.warnings:
            print(f"  - {w}")
    print("\nby language and tag:")
    for line in run.breakdown():
        print(f"  {line}")
    print()
    print(run.summary_line())
    print(f"report:       {paths['report'].as_posix()}")
    print(f"review sheet: {paths['review'].as_posix()}")
    _step_summary(run)


def _step_summary(run: RunResult) -> None:
    """Write the verdict and every new failure to the GitHub Actions job summary."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = [f"## {run.mode.value}: {'gate passed' if run.gate_passed else 'GATE FAILED'}", "",
             run.summary_line(), ""]
    bad = [r for r in run.results if r.status in ("fail", "unexpected_pass")]
    if bad:
        lines += ["| case | movement date | failed assertion |", "|---|---|---|"]
        for r in bad:
            for k in r.failed_checks() or []:
                msg = k.message.replace("|", "\\|")
                lines.append(f"| `{r.case.id}` | {r.case.movement_date} | **{k.name}**: {msg} |")
            if r.status == "unexpected_pass":
                lines.append(f"| `{r.case.id}` | {r.case.movement_date} | known failure now passes |")
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n\n")


def cmd_run(a) -> int:
    corpus = Corpus.load(a.policies)
    cases = load_cases(a.cases)
    known = load_known_failures(a.known)
    if a.agent_url:
        agent = HttpAgent(a.agent_url, timeout=a.timeout)
    else:
        agent = ReferenceAgent.from_snapshot(a.snapshot)
    run, transcript = run_live(agent, cases, corpus, known)
    save_transcript(transcript, a.transcripts)
    paths = write_outputs(run, a.out, corpus)
    print(f"recorded {len(transcript['entries'])} replies to {a.transcripts}")
    _print_run(run, paths)
    return 0 if run.gate_passed else 1


def cmd_replay(a) -> int:
    corpus = Corpus.load(a.policies)
    cases = load_cases(a.cases)
    known = load_known_failures(a.known)
    try:
        transcript = load_transcript(a.transcripts)
    except TranscriptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    run = replay(transcript, cases, corpus, known, transcript_path=Path(a.transcripts).as_posix())
    paths = write_outputs(run, a.out, corpus)
    _print_run(run, paths)
    return 0 if run.gate_passed else 1


def cmd_snapshot(a) -> int:
    corpus = Corpus.load(a.policies)
    path = write_snapshot(corpus, a.snapshot)
    print(f"wrote the reference agent's knowledge snapshot to {path.as_posix()}")
    for v in corpus.versions:
        print(f"  {v.document} v{v.version} from {v.effective_from}: {len(v.clauses)} clauses")
    return 0


def cmd_serve(a) -> int:
    root = Path(a.dir)
    if not root.exists():
        print(f"error: {root} does not exist; run 'evals run' or 'evals replay' first", file=sys.stderr)
        return 2
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ExclusiveServer(("127.0.0.1", a.port), handler)
    print(f"serving {root.as_posix()} at http://127.0.0.1:{a.port}/  (Ctrl+C to stop)")
    for name in sorted(p.name for p in root.glob("*.html")):
        print(f"  http://127.0.0.1:{a.port}/{name}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_serve_agent(a) -> int:
    agent = ReferenceAgent.from_snapshot(a.snapshot)
    server = make_server(agent, port=a.port)
    print(f"reference agent at http://127.0.0.1:{a.port}/ask  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evals", description="Regression tests for a procedures assistant.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--policies", default="policies", help="procedure documents folder")
        sp.add_argument("--cases", default="cases/procedures.yaml")
        sp.add_argument("--known", default="cases/known_failures.yaml")
        sp.add_argument("--transcripts", default=DEFAULT_TRANSCRIPT)
        sp.add_argument("--out", default="reports", help="where reports are written")

    r = sub.add_parser("run", help="LIVE: ask the agent every case and record its replies")
    common(r)
    r.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT), help="reference agent knowledge")
    r.add_argument("--agent-url", help="test an agent behind this JSON endpoint instead")
    r.add_argument("--timeout", type=float, default=10.0)
    r.set_defaults(fn=cmd_run)

    rp = sub.add_parser("replay", help="REPLAY: re-check recorded replies, no agent needed")
    common(rp)
    rp.set_defaults(fn=cmd_replay)

    s = sub.add_parser("snapshot", help="refresh the reference agent's knowledge from the procedure documents")
    s.add_argument("--policies", default="policies")
    s.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    s.set_defaults(fn=cmd_snapshot)

    sv = sub.add_parser("serve", help="serve the reports folder")
    sv.add_argument("--dir", default="reports")
    sv.add_argument("--port", type=int, default=DEFAULT_PORT)
    sv.set_defaults(fn=cmd_serve)

    sa = sub.add_parser("serve-agent", help="expose the reference agent as a JSON endpoint")
    sa.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    sa.add_argument("--port", type=int, default=DEFAULT_PORT)
    sa.set_defaults(fn=cmd_serve_agent)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
