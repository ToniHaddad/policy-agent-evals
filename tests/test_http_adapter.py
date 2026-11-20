"""The HTTP adapter, exercised against a real local stub server on port 8104."""

import json
import urllib.request

import pytest

from policy_evals.agent.base import AgentError, AgentRequest, ResponseFormatError
from policy_evals.agent.http import HttpAgent
from policy_evals.agent.stub_server import DEFAULT_PORT, make_server, serve_in_thread
from policy_evals.runner import replay, run_live

PORT = DEFAULT_PORT  # 8104, the port assigned to this project
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def stub(agent):
    server = make_server(agent, port=PORT, slow_seconds=1.5)
    serve_in_thread(server)
    yield BASE
    server.shutdown()
    server.server_close()


def test_health(stub):
    with urllib.request.urlopen(f"{stub}/health", timeout=5) as r:
        assert json.load(r)["agent"]["name"] == "reference-bm25"


def test_http_agent_matches_in_process_agent(stub, agent, cases, corpus, known):
    """The whole suite through HTTP gives the same verdicts as in-process."""
    http_run, transcript = run_live(HttpAgent(f"{stub}/ask"), cases, corpus, known)
    local_run, _ = run_live(agent, cases, corpus, known)
    assert [(r.case.id, r.status) for r in http_run.results] == [
        (r.case.id, r.status) for r in local_run.results]
    assert [r.response.to_json() for r in http_run.results] == [
        r.response.to_json() for r in local_run.results]
    assert transcript["agent"]["kind"] == "http"
    assert transcript["agent"]["url"].endswith("/ask")
    # Recorded HTTP replies replay like any other transcript.
    assert replay(transcript, cases, corpus, known).gate_passed


def test_arabic_survives_the_round_trip(stub):
    q = "ما هو الحد الأقصى لسعر الفندق في الليلة؟"
    r = HttpAgent(f"{stub}/ask").ask(AgentRequest(q, "lebanon", "2026-11-25", "ar"))
    assert r.action == "ask_clarification"


def test_missing_fields_raise_format_error(stub):
    with pytest.raises(ResponseFormatError, match="missing action, citations"):
        HttpAgent(f"{stub}/broken").ask(AgentRequest("q", "lebanon", None, "en"))


def test_http_500_raises_agent_error(stub):
    with pytest.raises(AgentError, match="HTTP 500"):
        HttpAgent(f"{stub}/error").ask(AgentRequest("q", "lebanon", None, "en"))


def test_timeout_raises_agent_error(stub):
    with pytest.raises(AgentError, match="within 0.3s"):
        HttpAgent(f"{stub}/slow", timeout=0.3).ask(AgentRequest("q", "lebanon", None, "en"))


def test_unreachable_agent_fails_cases_not_the_run(cases, corpus, known):
    """Port 9 (discard) is closed: every case fails with a clear message, no crash."""
    run, transcript = run_live(HttpAgent("http://127.0.0.1:9/ask", timeout=1), cases[:2], corpus, known)
    assert all(r.status == "fail" for r in run.results)
    msg = run.results[0].checks[0].message
    assert "cannot reach" in msg or "no reply" in msg  # Windows may time out before refusing
    assert "error" in transcript["entries"][0]["response"]


def test_headers_are_sent_but_not_recorded(stub):
    agent = HttpAgent(f"{stub}/ask", headers={"Authorization": "Bearer not-a-real-token"})
    assert "not-a-real-token" not in json.dumps(agent.describe())
    assert agent.ask(AgentRequest("Who approves an exception?", "kenya", "2026-11-24", "en")).action == "answer"


def test_second_server_on_a_taken_port_fails_loudly(stub, agent):
    with pytest.raises(OSError):
        make_server(agent, port=PORT)


def test_bad_action_is_rejected():
    from policy_evals.agent.base import AgentResponse
    with pytest.raises(ResponseFormatError, match="not one of"):
        AgentResponse.from_json({"answer": "x", "action": "maybe", "citations": []})
    with pytest.raises(ResponseFormatError, match="citation 0"):
        AgentResponse.from_json({"answer": "x", "action": "answer", "citations": [{"clause": "A"}]})
