"""Version-by-movement-date logic and the procedure parser."""

from datetime import date

import pytest

from policy_evals.policies import Corpus, PolicyFormatError, parse_policy


def test_documents_for_each_project(corpus):
    assert corpus.projects() == ["EA-2026", "FA-2026", "INKIND"]
    assert corpus.documents_for_project("FA-2026") == ["fa-2026-annex", "wh-procedure"]
    assert corpus.documents_for_project("INKIND") == ["inkind-annex", "wh-procedure"]
    assert corpus.documents_for_project("WASH-2026") == []
    assert corpus.documents_for_project("all") == []


@pytest.mark.parametrize(
    "day, version",
    [
        ("2026-01-14", None),  # before the first version
        ("2026-01-15", "1.0"),  # first day of v1.0
        ("2026-10-14", "1.0"),  # last day of v1.0
        ("2026-10-15", "2.0"),  # the change takes effect
        ("2027-06-01", "2.0"),
    ],
)
def test_version_in_force_by_movement_date(corpus, day, version):
    v = corpus.version_in_force("fa-2026-annex", date.fromisoformat(day))
    assert (v.version if v else None) == version


def test_retired_clause_is_absent_from_new_version(corpus):
    assert "FA-4.1" in corpus.get("fa-2026-annex", "1.0").clauses
    assert "FA-4.1" not in corpus.get("fa-2026-annex", "2.0").clauses
    assert corpus.get("fa-2026-annex", "2.0").clauses["FA-4.2"].replaces == "FA-4.1"


def test_retirement_lookup(corpus):
    r = corpus.retirement("fa-2026-annex", "FA-4.1")
    assert r.retired_in == "2.0"
    assert r.retired_from == date(2026, 10, 15)
    assert r.replaced_by == "FA-4.2"
    assert corpus.retirement("fa-2026-annex", "FA-2.1") is None


def test_snapshot_round_trip(corpus):
    again = Corpus.from_snapshot(corpus.to_snapshot())
    assert [(v.document, v.version, v.applies_to) for v in again.versions] == [
        (v.document, v.version, v.applies_to) for v in corpus.versions
    ]
    assert again.get("fa-2026-annex", "2.0").clauses == corpus.get("fa-2026-annex", "2.0").clauses
    assert again.fingerprint == corpus.fingerprint


def test_change_log_heading_is_not_a_clause(corpus):
    assert set(corpus.get("fa-2026-annex", "2.0").clauses) == {
        "FA-1.1", "FA-2.1", "FA-3.1", "FA-4.2", "FA-5.1", "FA-6.1"}


HEADER = "---\ndocument: d\ntitle: t\napplies_to: all\nversion: '1'\neffective_from: 2026-01-01\n---\n"


def test_parse_rejects_missing_front_matter():
    with pytest.raises(PolicyFormatError):
        parse_policy("## WP-1.1 Scope\ntext\n", "x.md")


def test_parse_rejects_missing_applies_to():
    with pytest.raises(PolicyFormatError, match="applies_to"):
        parse_policy(HEADER.replace("applies_to: all\n", "") + "## AA-1.1 One\na\n", "x.md")


def test_parse_rejects_duplicate_clause():
    with pytest.raises(PolicyFormatError):
        parse_policy(HEADER + "## AA-1.1 One\na\n## AA-1.1 Again\nb\n", "x.md")


def test_fingerprint_ignores_line_endings(tmp_path):
    for f in (tmp_path / "a", tmp_path / "b"):
        f.mkdir()
    text = HEADER + "## AA-1.1 One\na\n"
    (tmp_path / "a" / "p.md").write_bytes(text.encode())
    (tmp_path / "b" / "p.md").write_bytes(text.replace("\n", "\r\n").encode())
    assert Corpus.load(tmp_path / "a").fingerprint == Corpus.load(tmp_path / "b").fingerprint
