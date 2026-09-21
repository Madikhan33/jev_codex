# Testing and validation

Offline checks exercise routing contracts and installation behavior. Live evaluations
measure classifier predictions on supplied examples. Neither alone proves that every
Codex client can run every configured worker profile.

## Reproduce the offline checks

Use Python 3.11+ from the repository root:

```sh
python -m pip install ".[dev]"
python -m unittest discover -s tests -v
python scripts/smoke_install.py
python scripts/export_prompts.py
git diff --exit-code -- docs/PROMPTS.md
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
```

SDK contract tests intercept HTTP instead of calling TypeSafe; without the SDK they
are explicitly skipped. The smoke test uses a temporary installation and leaves your
Codex settings alone. Its `--online` flag downloads dependencies without calling Jev.
A symlink test may be skipped on systems without the required privilege.

The GitHub Actions configuration defines an OS/Python matrix. Consult the workflow
badge for actual run status; configuration alone is not evidence of passing runs.

## Coverage

| Area | Checks |
| --- | --- |
| Routing | Labels, thresholds, abstention, ownership grouping and profile mappings |
| Context | Session isolation, revision conflicts, expiry and bounded rerouting |
| Dispatch | Lifecycle transitions, retained ownership and escalation evidence |
| Team helpers | Research precedence, message bounds, duplicates and tool fallbacks |
| Installation | Hook merging, custom-file protection, rollback and uninstall |
| Credentials | Hidden entry, persistence and environment precedence |

For the 0.6.0 implementation on Windows with Python 3.12, 144 tests ran: 143 passed
and one symlink-privilege test was skipped. Lint, format, types, package build and
isolated installation passed. Re-run these checks for the revision you use.

## Optional live evaluation

Configure your TypeSafe key with `run.py configure`. Live evaluation makes paid
requests. Use synthetic or explicitly shareable input and save output locally:

```sh
python eval.py --cases tests/economy_cases.json --limit 12 --output .private/economy-report.json
```

Create `.private/` first. The evaluator uses the installed catalog by default.
`--catalog PATH` selects a complete alternative catalog containing the prompt TOML
files and `policy.toml`; `--config PATH` selects an alternative settings file.

Public fixtures contain authored expectations, not model predictions:

- `tests/cases.json`: category boundaries and controls.
- `tests/context_cases.json`: follow-ups with explicit context.
- `tests/economy_cases.json`: profile boundaries, escalation and ambiguity.
- `tests/worker_tasks.json`: separate implementation acceptance tasks.

Reports record fixture/catalog hashes, annotated metrics and failed cases. A missing
category fails its annotated profile check. Deliberate abstention may be expected.
Keep raw reports in `.private/`; sanitize findings before publishing them. Do not
silently change expected labels to match predictions.

## Current limits

A small 0.6.0 development run on 12 economic fixtures matched 11/12 profile expectations
(including abstention) and 9/12 complete annotated cases. One architecture category
remained uncertain; another case added a backend category; intent ambiguity also
caused failures. This is a development observation, not a held-out accuracy estimate
or a before/after benchmark. Raw local reports are not distributed publicly; use the
fixtures and evaluator to produce evidence for your setup.

Peer messaging depends on host tools, which may differ between workers; the lead can
relay messages when needed. Actual provider model identity, account access, general
routing accuracy and token savings are not established by offline checks. Include
classifier, lead, worker, retry and verification usage when measuring total costs.
`scripts/benchmark.py` measures local overhead and payload sizes, not model performance.
