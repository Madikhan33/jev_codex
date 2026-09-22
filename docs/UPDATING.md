# Updating Jev Router

After new changes are published, paste this into your local Codex:

```text
Update my installed Jev Router from https://github.com/Madikhan33/jev_codex.
Find its source checkout and inspect the README and installer. Back up local
changes before fetching and integrating updates; do not discard them or force-reset.
If the sources are missing, clone the repository into a separate directory.
Run install.py --without-key with Python 3.11+, then run.py doctor.
Preserve my API key, settings, other hooks and custom agent instructions.
Compare the installed classifier catalog with the new bundled prompts. Back up
the catalog before merging updates; preserve custom criteria and report conflicts.
Do not ask for my key in chat. Tell me what changed and any remaining steps,
including restarting Codex and reviewing /hooks if needed.
```

For a manual update, open a terminal in your **source checkout**, check `git status`
and commit or back up any local changes first. With a clean checkout, run:

```powershell
git pull --ff-only
py -3 install.py --without-key
py -3 run.py doctor
```

On macOS/Linux, replace `py -3` with `python3`. If you changed the source files
locally and just want to apply them, skip `git pull` and run the two Python commands.
An installation made from a ZIP needs a fresh release extracted into a separate
directory instead of `git pull`.

**Pulling code alone does not update Codex:** the installer must copy it into the
installed runtime. Updates are manual; there is no background auto-update.
Restart Codex afterward so its global `AGENTS.md` rule and agent profiles reload;
review `/hooks` if the changed hook needs trust again.
Credentials, settings and edited catalog files are preserved; explicit context disable settings are
preserved; missing context settings default to enabled.

**Classifier prompts need attention:** reinstalling preserves edited catalog files.
The unchanged older `profiles.toml` is migrated automatically to Luna xhigh/max and
Sol medium/high/xhigh. A customized older file is kept and must
be reconciled with those allowed efforts before installation can finish. Other new
criteria in `jev_router/prompts/` do not overwrite existing files. Back up
`~/.codex/jev-router/catalog` (Windows: `%USERPROFILE%\.codex\jev-router\catalog`),
then compare and merge changed prompts and policy. Use your actual installation
directory if customized. The Codex prompt above includes this step. If a managed
skill, agent file or the managed block in global `AGENTS.md` was edited, the installer
may stop to protect it: reconcile the
reported conflict before retrying. Only published changes are available through GitHub.
