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
| `contextual.py` | Classify relation to a fresh capsule before deciding whether to reuse its context |
| `session_state.py` | Bounded session/project capsules, expiry, revision checks and reroute guard |
| `session_commands.py` | Default context workflow, capsule CLI, assignment planning and reported trace |
| `dispatch.py` | Available-profile recommendations, ownership transitions and bounded local journal |

## Problems addressed

The original code had useful tests and a working two-stage design, but long command handlers mixed concerns, stable dictionaries lacked types, prompt text was split across code and generically named data files, and errors in one doctor check hid the rest of the report.

The refactor keeps the JSON routing contract, CLI entry points, environment keys and installed catalog filenames. Existing prompt-builder imports from `catalog.py` remain available, while implementations live in `questions.py`. There is no caching of submitted prompts or long-running background service.

Separate behavior fixes:

- Malformed policy numbers, examples and control labels fail validation before an API call.
- Multiple owners with unclear coordination use `coordinate_team`: dependencies remain unresolved and must be settled before parallel edits.
- Missing/null provider usage stays unknown without destroying an otherwise valid route.
- Unrelated empty hook groups survive reinstall/uninstall.
- Customized hooks matching either platform command cannot be duplicated silently.
- Printed doctor commands include the installation's settings path and PowerShell quoting.
- Hidden key entry refuses an echoing fallback when terminal secrecy is unavailable.

Prompt changes make category boundaries concise and give every independently evaluated question the same scope rules. Changes include Russian/English near-boundary examples, corrections, quoted input and documentation/test-only exclusions. These are authored improvements awaiting live evaluation, not measured accuracy gains.

See [validation and measurements](TESTING.md) and [the prompt source guide](../jev_router/prompts/README.md).

## Team orchestration

The hook classifies and emits advisory context; it does not spawn workers. The execution skill makes the main Codex the team lead. The lead turns ownership groups into bounded tasks using the original request, conversation and repository context. It records task ownership, dependencies, status and acceptance checks in the conversation, dispatches useful work, and integrates results. Workers report to the lead and must not recursively delegate.

Routing separates task assignment from permission to work in parallel:

| Condition | Strategy |
| --- | --- |
| Intent is unclear/unaccepted | `resolve_scope` |
| Accepted explanation/non-software intent | `single_agent` |
| No work groups for remaining intents | `resolve_scope` |
| Every group has `luna_low` | `single_agent` |
| One nontrivial group | `assign_specialist` |
| Multiple groups and accepted separable coordination | `consider_delegation` |
| Other multiple-group routes | `coordinate_team` |

Conditions above are evaluated in order. The compact v3 route adds `coordination`; unaccepted intent and coordination are exposed as `unclear`. `review_required` remains a request to review the routing recommendation. It is not a global execution gate, an independent code-review requirement or permission to discard user requirements. Uncertain categories and missing profiles remain visible without blocking clear work.

A single specialist is useful when the assignment is substantial and the lead has useful independent integration or acceptance work. Trivial edits do not need workers. With several groups, the lead resolves shared contracts and dependency order before parallel edits, gives each worker explicit ownership, and waits for prerequisites where necessary. A `coordinate_team` route does not imply all tasks can start at once.

When a profile is missing, the lead resolves it from local context and available profiles and labels the choice as its own. Neither the hook nor the classifier verifies account model access or changes the parent model. Runtime tools, available profiles and concurrency limits determine which assignments can actually run; unavailable delegation must be reported honestly.

Offline routing tests can validate strategy selection and metadata. They do not establish live classification accuracy, actual model availability, or end-to-end team behavior in Codex.

## Context-aware follow-ups

Context is enabled by default. An explicit `context_enabled: false` is preserved.
The skill maintains state without asking the user to enable a separate mode.
The lead saves a bounded capsule from its conversation context before delegation and
before its final answer. The hook never reads a transcript. It sends a fresh capsule
and current prompt to a relation classifier, then uses the capsule for work classification
only on continuation/correction/narrowing/approval/question. New-task and uncertain
relations exclude it; cancellation returns advice for the lead without spawning or
stopping workers. Completed state can explain corrections without becoming pending work.

The baseline pipeline has at most two logical calls. Fresh-context routing adds one;
an explicit lead reroute after resolving context is separately limited to once per turn
and at most two calls. The default hook timeout is 21 seconds. Capsules have a 24-hour
routing lifetime, a 6000-character limit, canonical session/project isolation and
compare-and-swap revisions. User/observed/assumption fact labels retain provenance.

The dispatch planner maps an available profile to configured model/effort, preserving
existing ownership for related work and requiring concrete reported evidence to escalate.
The lead makes the actual tool call. The journal validates reported lifecycle transitions;
it cannot establish backend model identity or independently validate reported evidence.
Null recommendations remain distinct from explicitly justified lead choices. The parent
model is unchanged. Comparative execution trials are separate from classifier fixtures;
the comparison tooling alone is not an executed model-quality benchmark.
