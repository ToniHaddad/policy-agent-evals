"""The deterministic checks: action, clause, version, in force, same decision."""

from policy_evals.agent.base import AgentResponse, Citation
from policy_evals.cases import Case, Expectation, label_warnings
from policy_evals.checks import run_checks
from policy_evals.policies import Corpus


def case(**kw) -> Case:
    base = dict(id="t", office="lebanon", travel_date="2026-11-20", language="en",
                question="q", expect=Expectation("answer", "LB-3.2", "2.0"))
    base.update(kw)
    return Case(**base)


def reply(action="answer", *cites) -> AgentResponse:
    return AgentResponse(answer="a", action=action,
                         citations=[Citation(d, v, c) for d, v, c in cites])


def by_name(results):
    return {r.name: r for r in results}


def test_all_pass_for_a_correct_reply(corpus):
    res = run_checks(case(), reply("answer", ("lb-travel", "2.0", "LB-3.2")), corpus)
    assert all(r.passed for r in res)
    assert set(by_name(res)) == {"action", "clause", "version", "in_force"}


def test_wrong_action(corpus):
    res = by_name(run_checks(case(), reply("escalate", ("lb-travel", "2.0", "LB-3.2")), corpus))
    assert not res["action"].passed
    assert res["action"].message == "expected action answer, agent chose escalate"


def test_wrong_clause(corpus):
    res = by_name(run_checks(case(), reply("answer", ("lb-travel", "2.0", "LB-4.1")), corpus))
    assert not res["clause"].passed
    assert "agent cited LB-4.1" in res["clause"].message


def test_retired_clause_is_caught_with_replacement_named(corpus):
    """The agent cites the old 7-day rule for a trip after the change."""
    res = by_name(run_checks(case(), reply("answer", ("lb-travel", "1.0", "LB-3.1")), corpus))
    assert not res["in_force"].passed
    assert res["in_force"].message == (
        "cited lb-travel v1.0 LB-3.1, but for travel on 2026-11-20 the version in force is "
        "lb-travel v2.0, where LB-3.1 is retired (retired from 2026-10-15, replaced by LB-3.2)")
    assert not res["version"].passed and not res["clause"].passed


def test_superseded_version_of_unchanged_clause(corpus):
    c = case(expect=Expectation("answer", "LB-4.1", "2.0"))
    res = by_name(run_checks(c, reply("answer", ("lb-travel", "1.0", "LB-4.1")), corpus))
    assert res["clause"].passed
    assert not res["version"].passed
    assert "superseded version" in res["in_force"].message


def test_invented_clause_and_version(corpus):
    res = by_name(run_checks(case(), reply("answer", ("lb-travel", "2.0", "LB-9.9"),
                                           ("lb-travel", "7.0", "LB-3.2")), corpus))
    msg = res["in_force"].message
    assert "that version has no clause LB-9.9" in msg
    assert "lb-travel has no version 7.0" in msg


def test_ask_case_skips_clause_checks(corpus):
    c = case(travel_date=None, expect=Expectation("ask_clarification"))
    res = by_name(run_checks(c, reply("ask_clarification"), corpus))
    assert set(res) == {"action"} and res["action"].passed


def test_agent_error_is_a_single_failure(corpus):
    res = run_checks(case(), AgentResponse.failed("HTTP 500 from x"), corpus)
    assert len(res) == 1 and not res[0].passed
    assert "HTTP 500" in res[0].message


def test_pair_must_reach_same_decision(corpus):
    en = case(id="en", pair="p")
    fr = case(id="fr", pair="p", language="fr")
    en_reply = reply("escalate", ("lb-travel", "2.0", "LB-3.2"), ("lb-travel", "2.0", "LB-6.1"))
    fr_reply = reply("answer", ("lb-travel", "2.0", "LB-6.1"))
    res = by_name(run_checks(fr, fr_reply, corpus, english=(en, en_reply)))
    assert not res["same_decision"].passed
    assert "English question led to escalate citing LB-3.2, LB-6.1" in res["same_decision"].message
    same = by_name(run_checks(fr, en_reply, corpus, english=(en, en_reply)))
    assert same["same_decision"].passed


def test_label_warnings_flag_stale_labels(changed_policies, cases):
    warnings = label_warnings(cases, Corpus.load(changed_policies))
    flagged = {w.split(":")[0] for w in warnings}
    assert flagged == {"kenya-hotel-100-december", "kenya-hotel-limit-december", "escalate-hotel-140-ke"}
