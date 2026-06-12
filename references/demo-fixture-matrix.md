# Demo Fixture Matrix

This document defines the sanitized fixture set used for final demos and
regression checks. The fixture runner is an observation/demo layer only: it
does not write Lark, send mail, generate production contracts, or advance real
candidate status.

## Why This Exists

The original `run_demo.py` is an installation smoke test with one mock
candidate. It proves the skill can load config and run basic modules, but it
does not cover the final demo story:

- multiple candidates and branches;
- S/A/B/C scoring outcomes;
- language-pair normalization;
- test invitation checkpoint;
- contract template selection;
- badcase governance;
- trace/span evidence for replay.

`scripts/run_fixture_demo.py` fills that gap without touching the production
business flow.

## Files

| Path | Purpose |
|---|---|
| `demo_fixtures/candidates.json` | Fictional candidate matrix and expected outcomes |
| `demo_fixtures/resumes/*.txt` | Sanitized resume text fixtures |
| `scripts/run_fixture_demo.py` | Runs the matrix and writes report/transcript/span evidence |
| `~/.loc-resume-demo-fixture-runs/<timestamp>/summary.md` | Human-readable run summary |
| `~/.loc-resume-demo-fixture-runs/<timestamp>/transcript.txt` | Terminal-style demo transcript |
| `~/.loc-resume-demo-fixture-runs/<timestamp>/fixture_demo_report.json` | Machine-readable report with sanitized spans |

## Candidate Coverage

| Fixture | Scenario | Expected |
|---|---|---|
| `DEMO-JA-0001` 青木遥 | Mainline strong candidate, Japanese, high confidence | S, test invitation checkpoint |
| `DEMO-KO-0002` 朴敏雅 | Complex bilingual language pair normalization | A, scoring checkpoint |
| `DEMO-EN-0003` Alex Chen | Medium-confidence word-count evidence | B, test-ready candidate |
| `DEMO-ES-0004` Lucía García | Low score and low confidence | C, review/reject branch |
| `DEMO-DE-0005` Meyer Studio GmbH | Overseas company, foreign currency contract | S, contract checkpoint |
| `DEMO-BAD-0006` Badcase Demo | Missing reliable word count | C, badcase snapshot checkpoint |

## Demo Actions

The runner includes three non-writing action checkpoints:

| Action | Fixture | What It Demonstrates |
|---|---|---|
| `test_email` | `DEMO-JA-0001` | Candidate, attachment, email and checkpoint flow |
| `contract` | `DEMO-DE-0005` | Contract info lookup and template choice explanation |
| `badcase` | `DEMO-BAD-0006` | Sanitized badcase snapshot protocol |

These actions intentionally do not send mail or create contracts. Production
TEST_MODE proof still belongs to `scripts/run_testmode_demo.py`, which calls
the real Lark-backed scripts.

## How To Run

```bash
python3 scripts/run_fixture_demo.py
```

The governance eval runner also includes this matrix:

```bash
python3 scripts/eval_runner.py --case demo_fixture_matrix
```

## Acceptance Rules

- Fixture expectations must be aligned to the current scoring engine output.
- A `changed` result means the fixture matrix caught a behavior difference; do
  not hide it for video polish.
- Demo fixture changes are considered sidecar/demo/eval changes unless they
  modify production scripts.
- Any final public demo must use generated or sanitized fixture data, not raw
  production resumes, contracts, emails, or payment records.

