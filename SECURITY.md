# Security and privacy

The integration intentionally sends the current user prompt to TypeSafe for
classification. Only use it for content that may be sent to that service. There
is no automatic personal-data or secret redaction, no offline Jev model, and no
claim about TypeSafe retention policy. Repository contents, transcript paths,
conversation transcripts and audio are not collected by this package. Context
(enabled by default; disable with `run.py session disable`) additionally sends a bounded task
summary maintained by the Codex lead. That summary can contain information learned
from the conversation. Save only necessary task facts, never secrets or full messages.
Disabling context stops external capsule use without deleting local state.

Capsules are partitioned by session and canonical project path, updated atomically with
revision checks, and expire for routing after 24 hours. Local files are not encrypted.
The dispatch journal contains bounded caller-reported evidence; it is not independently
verified provider telemetry. Do not put credentials in tool evidence or verification
descriptions. Session commands refuse symlink/junction storage paths. Clearing a capsule
creates a cancellation tombstone; it does not cancel running agents or erase the journal.

An optional key is stored in a local plaintext file only after the installer
explains that behavior and the user enters it. Environment-variable credentials
avoid this storage. Unix permissions are 0600 in a 0700 directory; Windows access
is inherited from the user profile. This is not an OS keychain. Never commit the
key. The `configure` command also explains plaintext storage before hidden input.
Uninstallation deletes the package's local credential file.

Hook input enters via stdin JSON, never by interpolating user text into a shell
command. Provider response values are validated against the local catalog before
anything is placed in model-visible developer context. Raw prompts, model-written
instructions and raw provider errors are not promoted to developer instructions.
This reduces an injection path; it does not establish adversarial robustness of
the classifier. Misclassification remains possible.

The installer does not alter Codex permissions, parent-model settings, approvals,
managed policies or hook-trust records. The registered local hook still needs
explicit review through /hooks. No dangerous trust bypass is installed. Existing
hooks are merged and backed up, not overwritten wholesale. Locally modified owned
files cause an installation conflict rather than silent replacement.

Hook failures continue without classification. A route is not authorization for
code changes, production operations, secret access, or a model-cost increase.
Custom agents inherit parent sandbox/approval controls; the package adds no broader
permissions. Source/catalog files are trusted local application configuration.

There is no configured public security-reporting endpoint yet. When publishing a
repository, enable private vulnerability reporting and add the maintainer contact
before accepting sensitive reports. Do not put exploitable secrets in public issues.
