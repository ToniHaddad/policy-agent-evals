# policy-agent-evals

Regression suite for a workplace policy assistant: catches it citing a
clause that is retired on the user's travel date. The system under test is
a deterministic reference agent (BM25 + rules); any agent behind a JSON
endpoint can be tested through the HTTP adapter. No LLM, no API key.

## Run and test
- `python -m venv .venv`, then `pip install -e .[dev]`
- `evals replay` re-checks `transcripts/reference-agent.json`, no agent needed
- `evals run` asks the reference agent live and rewrites that transcript
  (only `recorded_at` changes if the agent did not change; revert it if so)
- `evals snapshot` republishes the agent's knowledge from `policies/`
- `evals serve` serves `reports/` on 127.0.0.1:8104; `evals serve-agent`
  serves the agent at `/ask` on 8104 (one at a time)
- `pytest` (54 tests). The HTTP tests bind port 8104: stop any server first.

## Layout
- `policies/<office>/*.md` one file per version; `## XX-n.n Title` is a clause,
  `Replaces:` names the clause it retires
- `cases/travel.yaml` hand labels; `cases/known_failures.yaml` the gate's
  allow-list (strict: a listed case that passes fails the gate)
- `agent_knowledge/snapshot.json` what the reference agent knows (deliberately
  not read live from `policies/`, so a stale assistant can be shown)
- `policy_evals/` parser, agent, checks, runner (LIVE/REPLAY), report, review
- `tests/fixtures/` frozen policies and cases; unit tests never read the live
  ones, so a policy PR changes the eval job, not the unit tests

## Quirks
- On Windows, http.server's SO_REUSEADDR lets two servers share a port;
  `ExclusiveServer` turns it off so a taken port raises instead.
- PR #1 (policy change only) is left open and red on purpose; PR #2 fixes it.
