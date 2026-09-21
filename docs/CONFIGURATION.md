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
