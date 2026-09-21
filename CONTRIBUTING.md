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
evidence before claiming an accuracy, speed or cost improvement. Astra effort
remains limited to low/medium in this preset.

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

No automated release is configured. Follow [the launch checklist](docs/LAUNCH.md),
enable security reporting, and run live Codex/TypeSafe checks before release.
Do not describe a package as available from a registry before publication.
