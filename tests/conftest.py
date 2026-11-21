"""Unit tests run on a frozen copy of the procedures and cases in tests/fixtures.

That keeps them about the harness. Whether the agent passes on the live
procedures is the eval suite's job (``evals run`` / ``evals replay`` in CI),
so a procedure pull request changes the eval result, not these tests.
"""

import shutil
from pathlib import Path

import pytest

from policy_evals.agent.reference import ReferenceAgent
from policy_evals.cases import load_cases, load_known_failures
from policy_evals.policies import Corpus

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return Corpus.load(FIXTURES / "policies")


@pytest.fixture(scope="session")
def cases():
    return load_cases(FIXTURES / "cases.yaml")


@pytest.fixture(scope="session")
def known():
    return load_known_failures(FIXTURES / "known_failures.yaml")


@pytest.fixture(scope="session")
def agent(corpus) -> ReferenceAgent:
    return ReferenceAgent(corpus)


EA_V2 = """---
document: ea-2026-annex
title: Project annex EA-2026 (Emergency Appeal)
applies_to: EA-2026
version: "2.0"
effective_from: 2026-12-01
---

## EA-1.1 Scope
This annex applies to all stock funded by EA-2026.

## EA-2.2 Write-off approval
Replaces: EA-2.1
The operations manager approves damage write-offs of up to 40 pieces per
damage report. Above 40 pieces the emergency coordinator must also sign
before the write-off is recorded.

## EA-3.1 Dispatch destinations
EA-2026 stock may be dispatched only to the Organization's own centres and
to shelters the Organization runs. It may never be dispatched to a partner
organization.
"""


@pytest.fixture
def changed_policies(tmp_path) -> Path:
    """The fixture procedures plus an EA-2026 v2.0 that retires EA-2.1 from 2026-12-01."""
    dest = tmp_path / "policies"
    shutil.copytree(FIXTURES / "policies", dest)
    (dest / "ea-2026-annex-v2.0.md").write_text(EA_V2, encoding="utf-8")
    return dest
