"""Record and replay, and the rule that LIVE and REPLAY are never confused."""

import copy
import json

import pytest

from policy_evals.cli import main
from policy_evals.policies import Corpus
from policy_evals.report import render_report, report_names
from policy_evals.runner import (
    Mode, TranscriptError, load_transcript, replay, run_live, save_transcript,
)
from conftest import FIXTURES


def test_cli_replay_exits_1_on_a_policy_change(tmp_path, changed_policies, capsys):
    """The CI story end to end: replies recorded before the change fail after it."""
    snap, t, out = tmp_path / "snap.json", tmp_path / "t.json", tmp_path / "r"
    main(["snapshot", "--policies", str(FIXTURES / "policies"), "--snapshot", str(snap)])
    common = ["--transcripts", str(t), "--out", str(out), "--cases", str(FIXTURES / "cases.yaml"),
              "--known", str(FIXTURES / "known_failures.yaml")]
    assert main(["run", "--snapshot", str(snap), "--policies", str(FIXTURES / "policies"), *common]) == 0
    capsys.readouterr()
    assert main(["replay", "--policies", str(changed_policies), *common]) == 1
    printed = capsys.readouterr().out
    assert "FAIL  ea-writeoff-december" in printed
    assert "where EA-2.1 is retired" in printed
    assert "GATE FAILED" in printed


class NoAgent:
    """Fails the test if replay ever tries to reach an agent."""

    name = "none"

    def describe(self):
        return {"name": self.name}

    def ask(self, request):
        raise AssertionError("replay called an agent")


def verdicts(run):
    return {r.case.id: (r.status, [(c.name, c.passed, c.message) for c in r.checks]) for r in run.results}


def test_replay_reproduces_live_verdicts(agent, cases, corpus, known):
    live, transcript = run_live(agent, cases, corpus, known)
    replayed = replay(json.loads(json.dumps(transcript)), cases, corpus, known)
    assert live.mode is Mode.LIVE and replayed.mode is Mode.REPLAY
    assert verdicts(live) == verdicts(replayed)


def test_reference_agent_meets_the_gate(agent, cases, corpus, known):
    live, _ = run_live(agent, cases, corpus, known)
    assert live.gate_passed, [(r.case.id, r.failed_checks()) for r in live.results if r.status == "fail"]
    assert live.count("known_fail") == len(known)


def test_replay_never_calls_an_agent(agent, cases, corpus, known, monkeypatch):
    _, transcript = run_live(agent, cases, corpus, known)
    monkeypatch.setattr(type(agent), "ask", NoAgent.ask)
    run = replay(transcript, cases, corpus, known)
    assert run.gate_passed and run.agent["name"] == "reference-bm25"


def test_replay_catches_policy_change_in_recorded_replies(agent, cases, corpus, known, changed_policies):
    """Replies recorded before EA-2026 retired EA-2.1 fail against the new annex."""
    _, transcript = run_live(agent, cases, corpus, known)
    run = replay(transcript, cases, Corpus.load(changed_policies), known)
    failed = {r.case.id: r for r in run.results if r.status == "fail"}
    assert set(failed) == {"ea-writeoff-december", "ea-writeoff-limit-december"}
    msg = next(c for c in failed["ea-writeoff-december"].checks if c.name == "in_force").message
    assert "where EA-2.1 is retired (retired from 2026-12-01, replaced by EA-2.2)" in msg
    assert not run.gate_passed


def test_tampered_reply_is_caught(agent, cases, corpus, known):
    _, transcript = run_live(agent, cases, corpus, known)
    t = copy.deepcopy(transcript)
    entry = next(e for e in t["entries"] if e["case"] == "change-rule-on-day")
    entry["response"]["citations"] = [{"document": "fa-2026-annex", "version": "1.0", "clause": "FA-4.1"}]
    run = replay(t, cases, corpus, known)
    r = next(r for r in run.results if r.case.id == "change-rule-on-day")
    assert r.status == "fail"
    assert {c.name for c in r.failed_checks()} == {"clause", "version", "in_force"}


def test_missing_and_stale_transcripts_fail(agent, cases, corpus, known):
    _, transcript = run_live(agent, cases, corpus, known)
    t = copy.deepcopy(transcript)
    t["entries"] = [e for e in t["entries"] if e["case"] != "general-ledger"]
    next(e for e in t["entries"] if e["case"] == "general-fefo")["request"]["question"] = "old wording"
    run = replay(t, cases, corpus, known)
    by_id = {r.case.id: r for r in run.results}
    assert "no recorded reply" in by_id["general-ledger"].checks[0].message
    assert "different question" in by_id["general-fefo"].checks[0].message


def test_known_failure_that_passes_fails_the_gate(agent, cases, corpus):
    run, _ = run_live(agent, cases, corpus, {"project-partner-ea": "pretend it was broken"})
    r = next(r for r in run.results if r.case.id == "project-partner-ea")
    assert r.status == "unexpected_pass"
    assert not run.gate_passed


def test_reports_name_their_mode_and_never_the_other(agent, cases, corpus, known):
    live, transcript = run_live(agent, cases, corpus, known)
    rep = replay(transcript, cases, corpus, known)
    live_html, replay_html = render_report(live), render_report(rep)
    assert "<title>LIVE &middot;" in live_html and 'data-mode="LIVE"' in live_html
    assert "<title>REPLAY &middot;" in replay_html and 'data-mode="REPLAY"' in replay_html
    assert "REPLAY" not in live_html
    assert "LIVE" not in replay_html
    assert "No agent was called" in replay_html
    assert report_names(Mode.LIVE)["report"] != report_names(Mode.REPLAY)["report"]


def test_replay_refuses_a_results_file(tmp_path):
    p = tmp_path / "results-live.json"
    p.write_text(json.dumps({"mode": "LIVE", "results": []}))
    with pytest.raises(TranscriptError):
        load_transcript(p)


def test_cli_run_then_replay(tmp_path, capsys):
    t = tmp_path / "t.json"
    out = tmp_path / "reports"
    snap = tmp_path / "snapshot.json"
    pol = str(FIXTURES / "policies")
    assert main(["snapshot", "--policies", pol, "--snapshot", str(snap)]) == 0
    args = ["--transcripts", str(t), "--out", str(out), "--policies", pol,
            "--cases", str(FIXTURES / "cases.yaml"), "--known", str(FIXTURES / "known_failures.yaml")]
    assert main(["run", "--snapshot", str(snap), *args]) == 0
    assert "LIVE RUN" in capsys.readouterr().out
    assert main(["replay", *args]) == 0
    assert "REPLAY  no agent called" in capsys.readouterr().out
    assert {p.name for p in out.iterdir()} == {
        "report-live.html", "results-live.json", "review-sheet-live.html",
        "report-replay.html", "results-replay.json", "review-sheet-replay.html"}
    assert json.loads((out / "results-replay.json").read_text(encoding="utf-8"))["mode"] == "REPLAY"


def test_save_and_load_transcript(tmp_path, agent, cases, corpus, known):
    _, transcript = run_live(agent, cases[:3], corpus, known)
    p = save_transcript(transcript, tmp_path / "x" / "t.json")
    assert load_transcript(p)["entries"] == transcript["entries"]
