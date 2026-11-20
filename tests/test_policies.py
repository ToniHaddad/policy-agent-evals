"""Version-by-travel-date logic and the policy parser."""

from datetime import date

import pytest

from policy_evals.policies import Corpus, PolicyFormatError, parse_policy


def test_loads_both_offices(corpus):
    assert corpus.documents() == ["ke-travel", "lb-travel"]
    assert corpus.document_for_office("lebanon") == "lb-travel"
    assert corpus.document_for_office("colombia") is None


@pytest.mark.parametrize(
    "day, version",
    [
        ("2025-02-28", None),  # before the first version
        ("2025-03-01", "1.0"),  # first day of v1.0
        ("2026-10-14", "1.0"),  # last day of v1.0
        ("2026-10-15", "2.0"),  # the change takes effect
        ("2027-06-01", "2.0"),
    ],
)
def test_version_in_force_by_travel_date(corpus, day, version):
    v = corpus.version_in_force("lb-travel", date.fromisoformat(day))
    assert (v.version if v else None) == version


def test_retired_clause_is_absent_from_new_version(corpus):
    assert "LB-3.1" in corpus.get("lb-travel", "1.0").clauses
    assert "LB-3.1" not in corpus.get("lb-travel", "2.0").clauses
    assert corpus.get("lb-travel", "2.0").clauses["LB-3.2"].replaces == "LB-3.1"


def test_retirement_lookup(corpus):
    r = corpus.retirement("lb-travel", "LB-3.1")
    assert r.retired_in == "2.0"
    assert r.retired_from == date(2026, 10, 15)
    assert r.replaced_by == "LB-3.2"
    assert corpus.retirement("lb-travel", "LB-4.1") is None


def test_snapshot_round_trip(corpus):
    again = Corpus.from_snapshot(corpus.to_snapshot())
    assert [(v.document, v.version) for v in again.versions] == [
        (v.document, v.version) for v in corpus.versions
    ]
    assert again.get("lb-travel", "2.0").clauses == corpus.get("lb-travel", "2.0").clauses
    assert again.fingerprint == corpus.fingerprint


def test_change_log_heading_is_not_a_clause(corpus):
    assert set(corpus.get("lb-travel", "2.0").clauses) == {
        "LB-1.1", "LB-2.1", "LB-3.2", "LB-4.1", "LB-4.2", "LB-5.1", "LB-6.1", "LB-7.1", "LB-8.1"}


def test_parse_rejects_missing_front_matter():
    with pytest.raises(PolicyFormatError):
        parse_policy("## LB-1.1 Scope\ntext\n", "x.md")


def test_parse_rejects_duplicate_clause():
    text = "---\ndocument: d\ntitle: t\noffice: o\nversion: '1'\neffective_from: 2026-01-01\n---\n" \
           "## AA-1.1 One\na\n## AA-1.1 Again\nb\n"
    with pytest.raises(PolicyFormatError):
        parse_policy(text, "x.md")


def test_fingerprint_ignores_line_endings(tmp_path, corpus):
    for f in (tmp_path / "a", tmp_path / "b"):
        f.mkdir()
    text = "---\ndocument: d\ntitle: t\noffice: o\nversion: '1'\neffective_from: 2026-01-01\n---\n## AA-1.1 One\na\n"
    (tmp_path / "a" / "p.md").write_bytes(text.encode())
    (tmp_path / "b" / "p.md").write_bytes(text.replace("\n", "\r\n").encode())
    assert Corpus.load(tmp_path / "a").fingerprint == Corpus.load(tmp_path / "b").fingerprint
