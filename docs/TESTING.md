# Validation status

## Persistent context and dispatch (0.5.0)

- 123 tests ran successfully: 122 passed; one symlink-creation test was skipped
  because Windows did not grant the required privilege.
- Coverage includes session/project isolation, revision conflicts across processes,
  expiry, per-turn reroute limits, crash-released OS locks, dispatch lifecycle,
  profile retention, custom config propagation and relation ambiguity.
- The new live context-flow sample matched expected profiles in 5/6 cases with no
  transport failures. Client optimistic-save routing remains unresolved; use the
  explicit lead-selection fallback. This is a small development sample, not a
  held-out accuracy estimate. See `context-flow-live.json`; the initial 3/6 run and
  its prompt are preserved as `context-flow-baseline.json`/`.toml`.
- Actual `jev_luna_medium` and `jev_sol_medium` workers each implemented the same
  isolated pagination task. Both passed 19 independent pagination checks. See
  `worker-trials.json` and `worker-comparison.json`. One trial per profile, unknown
  cost/tokens, and no provider model telemetry: no general winner is established.
- Task capsule extraction remains the lead's skill-driven responsibility. The hook
  does not read transcripts; no claim that every client will execute the workflow
  correctly follows from the offline tests or these bounded live trials.

## Context evaluation (2026-09-21)

81 offline tests pass, including all seven profile-to-installed-agent model/effort
contracts and evaluator failure/abstention handling. These do not prove model access.
The new 24-case context suite and a bounded live eight-case sample are documented in
[context routing proposals and evidence](CONTEXT_ROADMAP.md). The frozen fixture and
raw report are retained there; two strict mismatches have ambiguous original labels.
No claim of general model-selection accuracy follows from this sample.

## Team orchestration update (2026-09-21)

- 69 offline tests passed, including assignment with uncertain categories, null profiles,
  coupled owners, rejected intent/coordination, and explanations that stay local.
- Ruff lint/format, mypy (12 modules), and skill structural validation passed.
- Independent read-only review covered five ownership/dependency/fallback scenarios.
  Its compact-intent ambiguity finding was fixed and covered by a regression assertion.
- Updated the local installation and verified source/runtime and skill byte equality.
  Existing config, hook definition, settings, credentials and catalog bytes were preserved.
  Doctor confirmed registration, integration integrity and configured key presence.
- No new paid classification calls or fresh-session end-to-end team benchmark were run.
  Restart Codex to reload the updated worker instructions before evaluating live behavior.

## Earlier refactor baseline

Checked on 2026-09-21, Windows, Python 3.12.4, TypeSafe SDK 0.7.0.

## Executed

- 61 tests passed, including the real SDK serialization/response contract with intercepted HTTP. No TypeSafe API call was made.
- Full isolated installer downloaded SDK dependencies, registered the hook and seven profiles, reinstalled without duplicate hooks, and uninstalled.
- The actual generated Windows hook command ran through PowerShell from a path with spaces. Disabled mode and missing-key fallback passed.
- Credential persistence/rotation, environment precedence, UTF-8 BOM settings, invalid enable flags and doctor registration checks passed.
- Existing-hook preservation, edited-file protection and parent-config preservation passed.
- Python wheel and source distribution built; the wheel includes catalog and skill resources.
- Skill structural validator passed.
- Ruff lint and formatting checks passed; mypy checked all 12 package modules.
- Independent read-only review approved the refactor after fixing duplicate Windows hook registration and the custom-install diagnostic command. The reviewer independently ran all 15 installer tests.

Evidence can be reproduced with:

```sh
python -m unittest discover -s tests -v
python scripts/smoke_install.py --online
python scripts/export_prompts.py
python -m build
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/benchmark.py
```

For the SDK contract test, install `typesafe-sdk>=0.7.0,<0.8` first. Without the SDK, that test is explicitly skipped. The smoke script uses only temporary installation paths and does not alter the user's Codex configuration. Its `--online` flag downloads dependencies, but does not call the classification API. Build requires the `build` package.

## Still unverified

- Real Jev classification accuracy and profile calibration.
- Prompt submission through a live Codex client and actual custom-agent model selection.
- macOS/Linux full installation and the remote Git-source installation command after publication.
- The GitHub Actions matrix itself; configuration is present but has not run locally.
- Adversarial robustness, throughput, latency, cost or token savings.

The old archive's Linux-only validation snapshot is superseded by this report. Offline success does not establish live service or Codex behavior.

## Opt-in live evaluation

`tests/cases.json` contains 44 authored expected examples, not recorded predictions. Added cases cover corrections, quoted instructions, documentation-only and tests-only work, frontend/server boundaries and short follow-ups with explicit context.
With uv and a configured TypeSafe key:

```sh
uv run eval.py --limit 5
```

This makes paid requests. The evaluator reports category precision/recall, exact matches, per-case duration and intent/profile accuracy only where fixtures include those labels. Missing categories count as failures for their annotated profiles. It does not measure end-to-end Codex code quality. Use synthetic/public input only. Include classifier, parent, workers, retries and verification when measuring total usage.

## Local performance measurements

On Windows / Python 3.12.4, using UTF-8 `json.dumps(..., ensure_ascii=False)` with its default separators:

| Question payload | Before this refactor | After |
| --- | ---: | ---: |
| Detection: 14 categories + 3 controls | 22,179 bytes | 18,859 bytes |
| Profiles: ui_layout + backend_api | 7,737 bytes | 5,782 bytes |

These are question bytes, not token counts or full HTTP request sizes. Category detection is about 15% smaller; the two-profile payload is about 25% smaller. No semantic accuracy or API-latency improvement follows from size alone.

`scripts/benchmark.py` measured median catalog loading at 4.307 ms over five samples of 100 loads. Timings vary by machine and run. Disabled hooks and control commands now bypass catalog loading; neither path imports the SDK. Network latency is unmeasured. The normal route still uses at most two calls and reuses one HTTP client; profiles for absent categories are never requested.
