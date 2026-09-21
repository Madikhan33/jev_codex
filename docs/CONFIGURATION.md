# Configuration and troubleshooting

## Installed layout

```text
~/.codex/jev-router/
  catalog/domains.toml     categories and boundary examples
  catalog/profiles.toml    models, effort, criteria and merge rank
  catalog/routing.toml     shared instructions and control questions
  catalog/policy.toml      thresholds, timeouts and input limits
  settings.json           enabled flag, catalog and credential paths
  secrets.json            optional plaintext key
  venv/                   private Python and SDK
  app/                    installed package copy
  manifest.json           managed file hashes and exact hook handler
~/.codex/agents/jev_*.toml
~/.agents/skills/jev-router/SKILL.md
```

`CODEX_HOME` changes the runtime root, not the default skills directory. Explicit paths:

```sh
python install.py --codex-home /custom/codex --skills-dir /custom/skills
python run.py doctor --config /custom/codex/jev-router/settings.json
python run.py configure --config /custom/codex/jev-router/settings.json
python install.py --codex-home /custom/codex --uninstall
```

Choose a skills directory Codex discovers. Custom directories are not automatically added to discovery. On Windows, use `py -3` if `python` is unavailable.

## Updates

In a clean source checkout:

```powershell
git pull --ff-only
py -3 install.py --without-key
py -3 run.py doctor
```

Preserve/reconcile local changes before pulling; do not reset them to force an update.
Use the same custom installation flags as before. Credentials and settings are retained;
an explicit context disable setting is retained; absent settings default to enabled. The default hook timeout is now 21 seconds, so the changed
hook definition can require renewed trust in `/hooks` after restarting Codex.

Rerun the installer to update the copied runtime and integrations. Keep the same installation paths; uninstall before relocating. Installed catalog changes are preserved. Compare upstream `jev_router/prompts/` and `jev_router/data/policy.toml` with the installed catalog to adopt new criteria deliberately. Legacy installations without `routing.toml` use bundled controls; reinstall adds the file for editing.

Changes to model IDs or efforts require reinstalling to regenerate agent TOML files. Criteria changes apply on the next hook invocation. Restart Codex after integration updates and inspect `/hooks`; changed commands can require trust review again.

Locally edited managed skill/agent files cause a conflict instead of being overwritten. Reconcile them with the source template. Uninstall also preserves changed files.

## Standalone use

```sh
python run.py classify "Add saving" --context "The form and API already exist; do not change the server."
python run.py classify "Implement cards UI and API" --top-k 5
```

Output includes accepted routes, uncertain categories, ownership groups, strategy and reported usage. `top-k` limits display candidates only, not accepted work or agent count.

`run.py` prefers the installed private interpreter. Set `JEV_ROUTER_FROM_SOURCE=1` to test the checkout with your selected interpreter. Calls use TypeSafe and may incur charges.

## Context and dispatch

If probability is split between several relations that all refer to the same task,
the router may emit `related_unspecified`. It reuses the capsule only when their
combined probability reaches the category acceptance threshold; the precise action
remains unresolved and must be interpreted from the user's message.

```powershell
# Optional: disable sending saved summaries
py -3 run.py session disable
# Restore the default later
py -3 run.py session enable
```

Add `--config /absolute/path/settings.json` for a custom installation. `context_enabled`
defaults to JSON `true`; `state_dir` defaults to `sessions` beside the settings file.
The default workflow sends the current prompt and saved task capsule to TypeSafe. It does
not read transcripts or create the initial capsule: the execution skill asks the lead
to maintain one from the conversation, before delegation and its final answer.

A capsule contains `task_id`, `objective`, `constraints`, `completed`, `pending`, `facts`,
`open_questions`, `owner`, and `status` (active/completed/cancelled). `turn_id` is optional.
Facts have `text` and `source` (user/observed/assumption). The rendered limit is 6000
characters. Capsules expire for routing after 24 hours and use revision-checked writes.
State is isolated by session and canonical project path; the lead must not guess IDs.

The trusted hook metadata supplies session/project/revision and exact runtime/config
paths. Use these with `session show`, `session save --expected-revision N`, and
`session clear --expected-revision N`. Supply capsule JSON on stdin. A revision conflict
requires re-reading and reconciling; clearing context does not stop real workers.

With fresh state, a relation classifier precedes work/profile classification: at most
three hook calls, compared with two without context. New-task/unclear relations exclude
old context from work classification. Cancellation skips those subsequent calls and
asks the lead to stop workers. An optional `session route --turn-id TURN` reroutes a
locally resolved prompt plus refreshed capsule, at most once per real turn and at most
two additional calls. Paid failures are not automatically retried by that command.

`session plan` accepts `{group, available_agents, existing, evidence}` on stdin. It
checks available role names and retains related ownership; it does not spawn. A lead
choice needs `selection_source: "lead"` and `selection_reason`. Escalation evidence uses
`new_constraints:<detail>`, `failed_check:<detail>` or `blocker:<detail>`; the prefix alone
does not prove the assertion. Availability comes from the actual Codex tool schema.

`session record` stores reported selected/dispatch_accepted/dispatch_failed/blocked/
stopped/completed events. Accepted assignments need an agent ID and tool evidence;
completion also needs verification. A running/blocked writer must stop before replacement.
`session trace` displays the bounded journal. Evidence is caller-reported, and
`actual_model_verified` remains false. The planner and journal never change the parent
model or prove backend model identity. See the [execution skill](../jev_router/resources/SKILL.md)
for exact event and assignment fields.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `python` opens Microsoft Store | Use `py -3` on Windows; install Python 3.11+ if absent |
| Hook does not run | Restart Codex; inspect `/hooks` for trust/enabled state and managed policies |
| Router unavailable warning | Run `run.py doctor`, then check key validity, quota and connectivity |
| Key works only in a terminal | Save it with `configure`, or restart Codex with the environment inherited |
| No subagents appear | Check separability, available tools, `[agents].enabled`, concurrency and model access |
| Model unavailable | Edit installed `profiles.toml` with supported IDs and reinstall |
| Reinstall reports conflict | Reconcile modified managed files without removing unrelated settings |
| `enabled` rejected | Use JSON `false`, not the string `"false"` |

`doctor` reports local registration and configuration warnings. Success does not prove live service or hook execution. A desktop installation can work without a `codex` CLI executable on PATH.

## Disable and remove

Set `enabled` to `false` in `settings.json`, set `JEV_ROUTER_DISABLE=1` in Codex's environment, or disable the handler in `/hooks`. Managed policies and existing disablement are respected.

Uninstall removes the exact registered handler, unchanged managed files and stored key. Modified handlers are preserved and reported for review in `/hooks`. Runtime, catalog and backups remain for inspection and can be removed after Codex exits. An old hooks backup is never restored over later changes.
