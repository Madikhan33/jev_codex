# Jev Router session workflow

This resource is conditional. Read it only when trusted hook metadata contains a
`session` object, as directed by [SKILL.md](SKILL.md). It carries the persistent context
and dispatch contracts separately from the compact team guidance.

## Persistent context and dispatch workflow

When trusted hook metadata contains `session`, context mode is enabled. Use exactly its
session_id, project, turn_id and revision; never guess identifiers or read transcripts.
The `session.runtime` object provides absolute interpreter and entry paths. Invoke those
as separate quoted arguments, followed by the commands below. Pass JSON on stdin, not
inside shell command interpolation. Always pass `--config` with session.runtime.config.

Before assigning ambiguous work, recover its meaning from the current conversation.
Distinguish continuation, correction, scope reduction, approval, cancellation, question,
and new task. A relation of `unclear` is not permission to reuse the last task blindly.
Use completed work as context for corrections/questions, not as pending work. Cancel
actual running workers before marking their assignment stopped; a hook label alone
cannot stop them. For a new task create a new task_id and clear inherited ownership.

1. Read state with `session show --session-id ID --project PATH` if the snapshot is
   missing, stale, or the revision is no longer current. A stale capsule may help local
   investigation but must be refreshed from the conversation before external routing.
2. Save a concise complete capsule before delegation and before the final reply for an
   ongoing software task: `session save --session-id ID --project PATH --expected-revision N`.
   Required stdin fields: `task_id`, `objective`, `constraints`, `completed`, `pending`,
   `facts`, `open_questions`, `owner`, `status`. Optional `turn_id` uses the actual turn.
   Lists contain short strings; facts are `{text, source}` with source `user`, `observed`
   or `assumption`. Owner is a string or null; status is active/completed/cancelled.
   Maximum rendered capsule: 6000 characters. Save only task facts required for future
   routing: no credentials, full messages, source files or unrelated personal information.
   Facts marked assumption must never be presented as confirmed requirements.
3. A revision conflict means another update won: re-read and reconcile with the latest
   user instruction, rather than blindly retrying the old capsule. Do not let a worker
   write the parent's capsule. If state is unavailable, continue locally and disclose it.
4. If the initial route was unresolved and local context now resolves it, optionally run
   `session route --session-id ID --project PATH --turn-id TURN` with stdin `{prompt: ...}`
   containing the current request. Save the refreshed capsule first. This sends the
   capsule to TypeSafe and permits only one explicit reroute per turn. Do not reroute an
   already useful recommendation, fabricate a turn_id, or retry a failed paid request.

Before spawning, use `session plan --session-id ID --project PATH` with stdin:
`{group: {...}, available_agents: [...], existing: null, evidence: []}`. Group includes
owner, profile and selection_source (`jev` or `lead`); lead choices also require a short
selection_reason. Populate available_agents from the actual tool schema. For the same
task, use its last trace assignment as existing (including owner/profile/agent_type/status).
A recommendation with missing context or unavailable role does not authorize a fabricated
spawn. Do not add arbitrary names to available_agents to make the planner pass.

Preserve the existing worker for related corrections. For the same task, a null new
recommendation can retain its already established available profile. Never reuse an
unrelated task's assignment. Escalation evidence must identify an actual new constraint,
failed check or blocker: `new_constraints:<detail>`, `failed_check:<detail>` or
`blocker:<detail>`. These are reported facts, not validation by string prefix. Criticism
or urgency alone is insufficient. Stop the old writer and record that fact before
replacement. A concrete failed check can justify moving beyond a bounded profile; it does
not prove that Astra is necessary.

Use `session record --session-id ID --project PATH` with stdin events for real assignments.
Start with status `selected`, task_id, agent_type, profile, owner and selection_source.
After the actual tool response, record `dispatch_accepted` with agent_id and short
`tool_evidence`; record `dispatch_failed` if no worker was accepted. Subsequent statuses:
blocked, stopped, completed. Carry the accepted agent_id through subsequent events.
Completion also requires `verification` describing checks actually performed. Do not mark
completed because the worker merely claims success. No recursive teams or concurrent
writers of the same files. `session trace` reads these bounded local records.

The journal validates ordering but its evidence is caller-reported, not provider telemetry.
Never set actual_model_verified=true. Explain the recommendation, selected profile, actual
tool outcome and any retained/fallback choice separately. Preserve the parent model.

`session clear --expected-revision N` (plus session/project) clears stored task content
with a cancellation tombstone; it does not stop workers. `session disable` turns off
external capsule use without deleting local state; `session enable` restores the default after an explicit disable. Context mode
sends the saved task summary as well as the current prompt to TypeSafe. Workers must not
save capsules, call session route, or independently reassign team ownership.

## Optional research and peer-message planners

The local planners in `jev_router/teamwork.py` do not browse, deliver messages or persist
state. They return caller-reported plans, so the lead still performs the selected action
and records actual evidence.

For `session research`, pass only the documented object fields `question`, `gap`,
`explicit_search`, `current`, `evidence_sufficient`, `web_allowed`, `web_available` and
`attempts`. The result selects `ask_user`, `inspect_local`, `search_web`, `report_gap` or
`proceed`; it does not execute the action. A fresh explicit search request (`attempts=0`)
takes precedence and can select web search even for a repository or requirements gap;
the result then carries `local_followup` as `inspect_local` or `ask_user`. Without that
fresh request, a requirements gap asks the user, a repository gap inspects local evidence
first, and current or external facts use web search when allowed and unresolved. Use
official sources and redacted queries for web work, then stop when the requested evidence
is sufficient. Do not add a classifier call.

For `session message`, pass only the documented `task_id`, `sender`, `recipient`, `kind`,
`body`, `evidence`, `roster`, `peer_messaging` and `previous_ids`. Use real same-team
agent IDs and statuses from the lead's live roster. The result may select
`send_peer`, `relay_via_lead`, `request_lead_followup`, `report_unavailable` or
`skip_duplicate`; it is not a delivery receipt. Keep messages bounded. Message kinds are
`question`, `answer`, `contract`, `blocker` and `result`; contract changes and blockers
notify the lead. Do not broadcast or poll.

An initial Astra plan must include nonempty `validate_evidence` reasons. Do not silently
fall back when that evidence is absent or the selected profile is unavailable.
