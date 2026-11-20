"""The reference agent: version by travel date, asking, escalating."""

from policy_evals.agent.base import AgentRequest
from policy_evals.agent.reference import ReferenceAgent, read_facts
from policy_evals.policies import Corpus


def ask(agent, q, office="lebanon", day="2026-11-20", lang="en"):
    return agent.ask(AgentRequest(q, office, day, lang))


def clauses(r):
    return [(c.clause, c.version) for c in r.citations]


def test_cites_version_in_force_on_each_side_of_the_change(agent):
    q = "How many days in advance must I submit my travel request?"
    assert clauses(ask(agent, q, day="2026-10-14")) == [("LB-3.1", "1.0")]
    assert clauses(ask(agent, q, day="2026-10-15")) == [("LB-3.2", "2.0")]


def test_same_days_different_decision_across_the_change(agent):
    q = "My trip leaves in 8 days. Can I still submit the travel request normally?"
    assert ask(agent, q, day="2026-10-10").action == "answer"
    r = ask(agent, q, day="2026-10-20")
    assert r.action == "escalate"
    assert ("LB-6.1", "2.0") in clauses(r)


def test_no_date_means_ask(agent):
    r = ask(agent, "How many days ahead do I need to book?", day=None)
    assert r.action == "ask_clarification" and r.citations == []


def test_missing_rate_means_ask(agent):
    assert ask(agent, "Is my hotel within the allowed rate?").action == "ask_clarification"


def test_offices_differ_on_the_same_rate(agent):
    q = "My hotel costs USD 115 per night. Is that within policy?"
    assert ask(agent, q, office="lebanon").action == "answer"
    ke = ask(agent, q, office="kenya")
    assert ke.action == "escalate"
    assert "Country Director" in ke.answer


def test_escalation_names_the_office_approver(agent):
    q = "My trip leaves in four days and the hotel is above the usual limit. What do I need?"
    r = ask(agent, q)
    assert r.action == "escalate"
    assert [c for c, _ in clauses(r)] == ["LB-3.2", "LB-4.1", "LB-6.1"]
    assert "Head of Office" in r.answer and "travel coordinator" in r.answer


def test_unknown_office_asks(agent):
    assert ask(agent, "What is the hotel limit?", office="colombia").action == "ask_clarification"


def test_read_facts():
    f = read_facts("My trip leaves in four days and the hotel costs $140")
    assert (f.days, f.rate) == (4, 140)
    assert read_facts("the hotel is above the usual limit").over_limit
    assert read_facts("Mon voyage part dans 4 jours").days is None  # English patterns only


def test_stale_snapshot_keeps_citing_what_it_knew(corpus, changed_policies):
    """The agent answers from its snapshot, not from the policy folder."""
    stale = ReferenceAgent(corpus)
    fresh = ReferenceAgent(Corpus.load(changed_policies))
    q = "My hotel in Kisumu is USD 100 per night. Is that within policy?"
    assert clauses(ask(stale, q, office="kenya", day="2026-12-14")) == [("KE-4.1", "1.0")]
    r = ask(fresh, q, office="kenya", day="2026-12-14")
    assert r.action == "escalate" and ("KE-4.3", "2.0") in clauses(r)
