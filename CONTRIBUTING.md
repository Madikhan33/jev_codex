# Contributing

Use Python 3.11+ and keep the standard-library-only unit tests runnable offline.
The only runtime service dependency is the official TypeSafe Python SDK.

The category source of truth is `jev_router/prompts/domains.toml`. A category change
must include positive examples, nearby negative examples, and a labeled regression
case. Use concrete questions and observable inclusion/exclusion criteria, not
personas, motivational language or instructions to understand a user's speech.
Avoid duplicated implementation categories that assign the same change twice.

Profile criteria and IDs live in `jev_router/prompts/profiles.toml`; shared rules
and control questions live in `jev_router/prompts/routing.toml`. Thresholds live
in `jev_router/data/policy.toml`.
Policy ordering does not establish model quality or price. Include real evaluation
evidence before claiming an accuracy, speed or cost improvement. Sol xhigh is the top
expert escalation profile and requires concrete evidence of an invariant conflict,
failed check or blocker.

```sh
python -m unittest discover -s tests -v
python scripts/export_prompts.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

`tests/cases.json` is authored expected behavior, not model output. A changed
expected label needs a short boundary explanation. Provider calls belong in
explicit opt-in evaluation, not the default unit suite. Never use real private
requests or keys in fixtures.

Install `typesafe-sdk>=0.7.0,<0.8` to include the real SDK contract test. It uses
intercepted HTTP and sends nothing to TypeSafe. `python scripts/smoke_install.py`
checks a temporary installation without dependencies; add `--online` to download
the SDK and exercise full installation and reinstallation, still without API calls.
Install development tools with `python -m pip install ".[dev]"`. Use
`python scripts/benchmark.py` for local loading overhead and question sizes;
these measurements exclude network latency and model quality.

Keep local experiment reports, terminal logs and session artifacts in `.private/`,
which is excluded from Git and source distributions. Public fixtures must be synthetic
or explicitly shareable. Before submitting, inspect `git diff --cached` for credentials,
personal paths and private task content. Ignore rules do not remove existing Git history.

No automated release is configured. Before release, run the checks above, build the
package, inspect its contents, and test installation from a clean environment. Report
live Codex/TypeSafe results separately from offline tests. Enable a private security
reporting channel before accepting sensitive reports. Do not describe a package as
available from a registry before publication.
