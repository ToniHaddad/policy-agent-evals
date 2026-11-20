"""Unit tests run on a frozen copy of the policies and cases in tests/fixtures.

That keeps them about the harness. Whether the agent passes on the live
policies is the eval suite's job (``evals run`` / ``evals replay`` in CI),
so a policy pull request changes the eval result, not these tests.
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


KENYA_V2 = """---
document: ke-travel
title: Northbridge Relief Kenya Office, Staff Travel Policy
office: kenya
version: "2.0"
effective_from: 2026-12-01
---

## KE-1.1 Scope
Applies to all Kenya office staff.

## KE-3.1 Advance booking
Submit the travel request at least 5 calendar days before departure.

## KE-4.3 Hotel ceiling
Replaces: KE-4.1
The hotel rate may not exceed USD 90 per night, including breakfast.

## KE-6.1 Exceptions
Any departure from sections 3 or 4 needs an exception approved by the
Country Director.
"""


@pytest.fixture
def changed_policies(tmp_path) -> Path:
    """The fixture policies plus a Kenya v2.0 that retires KE-4.1 from 2026-12-01."""
    dest = tmp_path / "policies"
    shutil.copytree(FIXTURES / "policies", dest)
    (dest / "ke-travel-v2.0.md").write_text(KENYA_V2, encoding="utf-8")
    return dest
