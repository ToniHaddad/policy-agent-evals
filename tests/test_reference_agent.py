"""The reference agent: version by movement date, asking, escalating."""

from policy_evals.agent.base import AgentRequest
from policy_evals.agent.reference import ReferenceAgent, read_facts
from policy_evals.policies import Corpus


def ask(agent, q, project="FA-2026", day="2026-11-20", lang="en", wh="WH-12"):
    return agent.ask(AgentRequest(q, project, wh, day, lang))


def clauses(r):
    return [(c.clause, c.version) for c in r.citations]


def test_cites_version_in_force_on_each_side_of_the_change(agent):
    q = "How many days before expiry must stock be released or reported?"
    assert clauses(ask(agent, q, day="2026-10-14")) == [("FA-4.1", "1.0")]
    assert clauses(ask(agent, q, day="2026-10-15")) == [("FA-4.2", "2.0")]


def test_same_days_different_decision_across_the_change(agent):
    q = "The lentils expire in 40 days. Do I need to do anything?"
    assert ask(agent, q, day="2026-10-10").action == "answer"
    r = ask(agent, q, day="2026-10-20")
    assert r.action == "escalate" and clauses(r) == [("FA-4.2", "2.0")]


def test_no_project_or_no_date_means_ask(agent):
    assert ask(agent, "Can I send kits to a partner?", project=None).action == "ask_clarification"
    assert ask(agent, "Can I send kits to a partner?", project="WASH-2026").action == "ask_clarification"
    r = ask(agent, "The lentils expire in 40 days.", day=None)
    assert r.action == "ask_clarification" and r.citations == []


def test_damage_without_a_quantity_means_ask(agent):
    assert ask(agent, "Some boxes were crushed. Can I write them off?").action == "ask_clarification"
    r = ask(agent, "8 boxes of soap were damaged. Can I write them off?")
    assert r.action == "ask_clarification" and "pieces are in each box" in r.answer


def test_boxes_are_converted_to_pieces(agent):
    r = ask(agent, "12 boxes + 6 pieces of canned cheese (24 per box) were damaged.")
    assert r.action == "escalate"
    assert "294 pieces is above 50, so the FA-2026 project manager must also sign" in r.answer


def test_projects_differ_on_transfers(agent):
    q = "Can I transfer 40 pieces of rice from this project to another project?"
    assert ask(agent, q, project="FA-2026").action == "answer"
    assert ask(agent, q, project="EA-2026").action == "escalate"
    assert clauses(ask(agent, q, project="INKIND")) == [("IK-5.1", "1.0")]


def test_write_off_names_the_project_co_signer(agent):
    q = "120 pieces of canned cheese were damaged in the flood."
    r = ask(agent, q, project="EA-2026")
    assert r.action == "escalate"
    assert [c for c, _ in clauses(r)] == ["EA-2.1", "WP-6.1"]
    assert "emergency coordinator must also sign" in r.answer
    small = ask(agent, "60 pieces were damaged.", project="EA-2026")
    assert "within the operations manager's limit of 100" in small.answer


def test_expired_stock_cites_the_expired_stock_clause(agent):
    """Regression: a loose title match once cited WP-4.1 'First expired, first out'."""
    r = ask(agent, "The juice expired last week. Can I dispatch it?", project="INKIND")
    assert r.action == "escalate" and clauses(r) == [("WP-6.2", "1.0")]


def test_read_facts():
    f = read_facts("The rice expires in four days and 30 pieces were damaged")
    assert (f.expiry_days, f.pieces, f.damage) == (4, 30, True)
    assert read_facts("12 boxes + 6 pieces (24 per box)").pieces == 294
    assert read_facts("Two dozen cans got crushed").pieces is None  # known gap
    assert read_facts("30 pièces endommagées").damage is False  # English patterns only


def test_stale_snapshot_keeps_citing_what_it_knew(corpus, changed_policies):
    """The agent answers from its snapshot, not from the procedure folder."""
    stale = ReferenceAgent(corpus)
    fresh = ReferenceAgent(Corpus.load(changed_policies))
    q = "45 pieces of baby formula were damaged. Who approves the write-off?"
    assert clauses(ask(stale, q, project="EA-2026", day="2026-12-08"))[0] == ("EA-2.1", "1.0")
    r = ask(fresh, q, project="EA-2026", day="2026-12-08")
    assert clauses(r)[0] == ("EA-2.2", "2.0")
    assert "emergency coordinator must also sign" in r.answer
