# Runtime and storage contract

Read this reference when the campaign runs outside a single local workspace, when multiple campaigns or users exist, or when recovery, migration, concurrency, or database storage matters.

The full game semantics and file responsibilities remain defined by [ruleset.md](ruleset.md). This document maps those logical records to portable runtimes.

New v1.6 records conform to [campaign-state.schema.json](campaign-state.schema.json), [campaign-event.schema.json](campaign-event.schema.json), and [portable-anchor.schema.json](portable-anchor.schema.json). These contracts do not authorize automatic migration of an older campaign.

## Logical records

Every storage backend must expose these records without changing their meaning:

- active campaign pointer
- latest authoritative state
- append-only event log
- player-visible journal
- canon deviation log
- latest portable anchor
- processed ingress identifiers
- pending and delivered outbound messages
- generated media metadata
- private RNG configuration and public seed commitment; the private seed itself stays in a secret store

Local files, SQLite, PostgreSQL, object storage, or an Agent platform database may implement the records. Storage choice cannot change adjudication.

When the ruleset names `state.yaml`, `events.jsonl`, `journal.md`, `canon-deviations.md`, `latest-anchor.md`, or `active.yaml`, a service runtime may satisfy that rule through the corresponding logical record below. The filename expresses record semantics, not a mandatory physical storage engine.

## Campaign scope

Use a stable scope key before resolving the active campaign:

```text
<platform>:<agent-or-bot-id>:<conversation-id>:<thread-id-or-0>:<player-scope>
```

Examples:

```text
local:codex:example-project:0:single
telegram:example-bot:example-group:example-thread:shared
telegram:example-bot:example-user-chat:0:example-user
```

Private chats normally use one campaign per chat. Group and forum chats must explicitly choose either a shared campaign or one campaign per player. Never use one global active pointer for an entire bot service.

## Local filesystem profile

For a single-player workspace, preserve the ruleset layout:

```text
campaigns/
├── active.yaml
└── <campaign_id>/
    ├── state.yaml
    ├── events.jsonl
    ├── journal.md
    ├── canon-deviations.md
    └── latest-anchor.md
```

Generated panels and illustrations belong under a campaign media directory or external media store and must not be treated as authoritative state.

When local Python is available, use the bundled runtime helper instead of hand-editing records:

```bash
python3 scripts/campaign_runtime.py validate --campaign-dir campaigns/<campaign_id>
python3 scripts/campaign_runtime.py commit --campaign-dir campaigns/<campaign_id> --event pending-event.json
python3 scripts/campaign_runtime.py recover --campaign-dir campaigns/<campaign_id>
python3 scripts/campaign_runtime.py export-anchor --campaign-dir campaigns/<campaign_id> --output portable-anchor.json
```

The helper writes JSON text to `state.yaml`; JSON is valid YAML 1.2 and keeps the no-dependency path deterministic. It also reads block-style YAML when PyYAML is installed.

## Multi-tenant service profile

A service may map the same records to tables or namespaced objects:

```text
campaign_scopes(scope_key, active_campaign_id, state_revision)
campaign_states(campaign_id, state_revision, state_json, updated_at)
campaign_events(campaign_id, event_id, ingress_id, payload_json, created_at)
campaign_documents(campaign_id, kind, revision, body)
processed_ingress(scope_key, ingress_id, result_event_id)
transport_outbox(outbox_id, campaign_id, event_id, payload, status, platform_message_id)
campaign_media(media_id, campaign_id, event_id, kind, public_facts_hash, platform_file_id)
campaign_rng(campaign_id, method, next_counter, seed_commitment, secret_ref)
```

The physical schema may vary. The uniqueness and transaction constraints may not:

- unique `(campaign_id, event_id)`
- unique `(scope_key, ingress_id)`
- one active campaign pointer per scope
- state commit uses expected `state_revision`
- one outbox record per intended message or media item

## Turn transaction

1. Deduplicate the transport ingress identifier.
2. Lock the campaign scope or begin a serializable transaction.
3. Read active campaign, latest state, and last event.
4. Recover any event appended after the last committed state.
5. For a risky action, construct and deliver the public stakes specification; allow the player to revise an unrolled approach. This pre-roll exchange does not create a game event or advance world time.
6. Generate the raw die through an approved RNG and immediately bind it to a stable context and counter.
7. Adjudicate once and produce one primary event containing stakes, RNG metadata, consequences, and an old-value-checked `state_patch`.
8. Append the complete event.
9. Apply the patch and compare-and-swap state from the expected revision to the next revision.
10. Update player-visible documents.
11. Create transport outbox records in the same transaction when possible.
12. Commit before sending messages.
13. Deliver outbox items idempotently and record platform message identifiers.

If delivery fails after commit, retry delivery from the outbox. Never re-adjudicate the action.

## Ingress metadata

Each externally triggered action records enough data to deduplicate and audit it:

```yaml
transport:
  platform: telegram
  scope_key: "telegram:example-bot:example-user-chat:0:example-user"
  ingress_id: "update:example-update"
  conversation_id: "example-user-chat"
  thread_id: null
  actor_id: "example-user"
  message_id: "example-message"
  callback_id: null
```

Button callbacks use the callback query identifier as an additional ingress identifier. An edited message does not silently replace an already adjudicated action; treat it as a new request to clarify or correct.

## Concurrency and recovery

- Serialize turns per campaign scope, not globally across the service.
- Reject or retry compare-and-swap conflicts after reloading state; never overwrite a newer revision.
- Store rolls inside the event before narrative delivery.
- Recover appended events from their recorded `state_patch` without rerolling.
- Keep real timestamps separate from world time.
- Media jobs may run concurrently after the event commits because they cannot mutate game truth.

`state_patch` uses `add`, `replace`, and `remove` operations with JSON Pointer paths. `replace` and `remove` carry the expected old value; a mismatch stops the commit rather than overwriting newer state. Revision, last event ID, and real update time are runtime-managed fields and cannot appear in a patch.

## Randomness contract

Use `scripts/roll_check.py` when local execution exists:

```bash
python3 scripts/roll_check.py init-seed --output /private/runtime/<campaign_id>.seed
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 \
  --context evt-000042:inspect-door --seed-file /private/runtime/<campaign_id>.seed --counter 17
```

The default `roll` mode uses the operating system CSPRNG. Seeded mode derives each d100 with HMAC-SHA256 and rejection sampling from a private 256-bit seed, a monotonically increasing counter, and stable context. Record the commitment, counter, context, raw value, and adjudication; never record or export the seed. A platform RNG is acceptable only when its success response or result identifier can be stored with the event.

## Secrets and hidden state

Transport tokens, database credentials, signing secrets, and webhook secrets live in the deployment secret store. They never enter campaign state, events, prompts, screenshots, logs intended for players, or the reusable skill package.

Hidden engine records must be accessible to the adjudicator and inaccessible to player-facing renderers. Treat file separation as organization; enforce actual access control in service deployments.

## Portable fallback

If durable storage is unavailable, emit the complete latest anchor required by the ruleset and mark the campaign as degraded. The v1.6 anchor contains authoritative hidden state, recent events, and a canonical SHA-256 digest; warn that it contains spoilers and do not expose it in a group chat. Do not claim persistence. When durable storage returns, verify the digest, import the anchor once, create a migration event, and resume append-only history.
