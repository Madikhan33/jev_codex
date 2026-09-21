# Launch guide

## Positioning

Suggested GitHub About text:

> Task-aware routing for Codex: classify prompts with Jev, select model profiles, and delegate scoped work through native subagents.

Suggested topics: `codex`, `agent-skills`, `subagents`, `task-routing`, `typesafe`, `python`, `developer-tools`.

Lead with a concrete workflow: one UI-plus-API prompt, two owners, scoped assignments and a verified combined result. Explain that the parent model is unchanged.

## Before release

- Publish the source, then test the Git-source install command from a clean environment.
- Run the offline matrix and SDK contract tests; verify each claimed platform.
- Test real TypeSafe classification and a Codex session: trusted hook, worker creation, actual model/effort, completed task and integration checks.
- Record Codex, Python and SDK versions with sanitized outputs.
- Enable private vulnerability reporting and update SECURITY.md with the working channel.
- Create a version tag after validation and document a pinned Git install command.
- Record a real demo. Mark synthetic examples explicitly.

## Demo outline

1. Install from a clean checkout; hide credential entry entirely.
2. Trust the hook and submit a UI-plus-API request.
3. Show the route and actual worker assignments.
4. Show the finished integration and checks.
5. Demonstrate a small change staying with one owner.

Add the demo to README after recording a real run. Avoid screenshots of invented metrics.

## Share with evidence

Suggested announcement:

> I built Jev Codex Router, an open source routing layer for local Codex. It classifies requests with Jev, groups related work, and supplies model profiles to a skill that coordinates native subagents. The installer sets up the hook and profiles; criteria are editable. I am looking for reproducible routing examples and compatibility reports.

Share where announcements are welcome: relevant GitHub discussions, developer communities and your own channels. Respond with concrete reproductions and fixes. No automated outreach is included.

Before claiming savings, compare equivalent tasks and include classifier, parent, worker, repeated-context, retry and verification usage. Report latency separately from tokens and monetary cost.

## Presentation references

The [uv README](https://github.com/astral-sh/uv) puts the product statement, installation and concrete examples near the top. [GitHub's README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) covers purpose, usefulness, getting started and help. This project follows that information order without borrowing performance claims.
