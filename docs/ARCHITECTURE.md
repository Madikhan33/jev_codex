# Code map and refactor notes

## Request path

```text
cli.py → hook.py → settings.py + catalog.py
                         ↓
                  questions.py ← prompts/*.toml
                         ↓
                    sdk.py → TypeSafe
                         ↓
                    routing.py → compact route → Codex skill
```

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse commands and delegate to handlers; imports expensive paths only when needed |
| `hook.py` | Read bounded stdin, skip disabled/control input, emit context or a safe fallback |
| `catalog.py` | Load and validate editable prompts and policy; support legacy installed catalogs |
| `questions.py` | Build actual TypeSafe questions from prompt text |
| `contracts.py` | Document stable internal data shapes with TypedDict; preserve v3 output keys |
| `routing.py` | Validate answers, apply thresholds, select ownership and execution strategy |
| `sdk.py` | Convert questions into SDK objects and reuse one bounded HTTP client |
| `settings.py` | Local settings and explicit credential entry/readback |
| `diagnostics.py` | Local readiness checks without a provider request |
| `installer.py` | Preflight, runtime staging, registration, rollback and selective uninstall |
| `storage.py` | Atomic writes and hashes shared by settings and installation |

## Problems addressed

The original code had useful tests and a working two-stage design, but long command handlers mixed concerns, stable dictionaries lacked types, prompt text was split across code and generically named data files, and errors in one doctor check hid the rest of the report.

The refactor keeps the JSON routing contract, CLI entry points, environment keys and installed catalog filenames. Existing prompt-builder imports from `catalog.py` remain available, while implementations live in `questions.py`. There is no caching of submitted prompts or long-running background service.

Separate behavior fixes:

- Malformed policy numbers, examples and control labels fail validation before an API call.
- Multiple owners with unclear coordination preserve `resolve_scope` instead of appearing resolved.
- Missing/null provider usage stays unknown without destroying an otherwise valid route.
- Unrelated empty hook groups survive reinstall/uninstall.
- Customized hooks matching either platform command cannot be duplicated silently.
- Printed doctor commands include the installation's settings path and PowerShell quoting.
- Hidden key entry refuses an echoing fallback when terminal secrecy is unavailable.

Prompt changes make category boundaries concise and give every independently evaluated question the same scope rules. Changes include Russian/English near-boundary examples, corrections, quoted input and documentation/test-only exclusions. These are authored improvements awaiting live evaluation, not measured accuracy gains.

See [validation and measurements](TESTING.md) and [the prompt source guide](../jev_router/prompts/README.md).
