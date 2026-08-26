# Runtime and storage contract

Read this reference when the campaign runs outside a single local workspace, when multiple campaigns or users exist, or when recovery, migration, concurrency, or database storage matters.

The game semantics and their authority map are defined by [ruleset.md](ruleset.md). This document only maps the continuity contract to portable runtimes.

New v1.7 records conform to [campaign-state.schema.json](campaign-state.schema.json), [campaign-event.schema.json](campaign-event.schema.json), and [portable-anchor.schema.json](portable-anchor.schema.json). Legacy v1.6 records remain valid against the `.v1.6.schema.json` files. Neither contract authorizes automatic migration of an older campaign.

Pre-contract v1.2 through v1.5 ledgers have no compatible `state_patch` transaction schema. The bundled validator can identify their version, verify their basic event and revision continuity, and report `valid_legacy_read_only`; commit, recovery, initialization, and portable-anchor export remain disabled until an explicit migration creates a writable contract. This protects old campaigns without pretending they already satisfy v1.6.

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

## Rule context cache

Every adjudication request includes [runtime-core.md](runtime-core.md). A deployment may cache the larger rule modules by the `ruleset_digest` declared in [rules-manifest.json](rules-manifest.json), but the cached content must remain accessible to the model that performs the adjudication. A database receipt without the corresponding text is not a valid cache hit.

Keep rule context cache outside campaign truth. It may record the profile ID, ruleset digest, verified module names, content bytes or an immutable prompt-prefix reference, and verification time. Never use it as a game event or let a cache miss advance world time. On a digest mismatch, discard the old context and follow the bootstrap loading route before adjudicating.

For ordinary turns, construct a revision-bound working set containing the fields required by [runtime-core.md](runtime-core.md). Bind it to the source `state_revision` and preferably a canonical state digest. Load only the recent and prerequisite events required for the action; fetch more authoritative slices when the router or adjudicator detects a missing dependency. If the projection is stale or incomplete, fall back to the full state rather than guessing.

## Campaign scope

Use a stable scope key before resolving the active campaign:

```text
<platform>:<agent-or-bot-id>:<conversation-id>:<thread-id-or-0>:<player-scope>
```

Examples:

```text
local:codex:example-project:0:single
telegram:example-bot:example-group:example-thread:controller-example-user
telegram:example-bot:example-user-chat:0:example-user
```

Private chats normally use one campaign per chat. Group and forum chats must choose either one campaign per player or a shared-view campaign with one configured controller. v1.7 does not support multiple players concurrently controlling one protagonist; spectators cannot create game events. Never use one global active pointer for an entire bot service.

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
campaign_controllers(scope_key, actor_id, status)
ruleset_context_cache(ruleset_digest, profile_id, content_ref, verified_modules, verified_at)
```

The physical schema may vary. The uniqueness and transaction constraints may not:

- unique `(campaign_id, event_id)`
- unique `(scope_key, ingress_id)`
- one active campaign pointer per scope
- at most one active controller per v1.7 single-protagonist scope
- state commit uses expected `state_revision`
- one outbox record per intended message or media item

## Turn transaction

1. Resolve the scope and verify that the actor is the configured controller. Spectator input may be stored as discussion but cannot enter adjudication.
2. Deduplicate the transport ingress identifier.
3. Lock the campaign scope or begin a serializable transaction.
4. Read active campaign and a revision-bound turn working set plus the last event. Fetch missing authoritative slices or the full state before adjudication when required.
5. Recover any event appended after the last committed state.
6. For a risky action, construct and deliver the public stakes specification; allow the player to revise an unrolled approach. This pre-roll exchange does not create a game event or advance world time.
7. Generate the raw die through an approved RNG and immediately bind it to a stable context and counter.
8. Adjudicate once and produce one primary event containing stakes, RNG metadata, consequences, and an old-value-checked `state_patch`.
9. Append the complete event.
10. Apply the patch and compare-and-swap state from the expected revision to the next revision.
11. Update player-visible documents.
12. Create transport outbox records in the same transaction when possible.
13. Commit before sending messages.
14. Deliver outbox items idempotently and record platform message identifiers.

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
- Deterministic status media and optional illustration jobs may run concurrently after the event commits because they cannot mutate game truth. Send required status text first when rendering is delayed; optional illustration work never blocks the next player action.

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

If durable storage is unavailable, emit the complete latest anchor required by the ruleset and mark the campaign as degraded. The v1.7 anchor uses format 1.1 and contains authoritative hidden state, recent events, and a canonical SHA-256 digest; warn that it contains spoilers and do not expose it in a group chat. Do not claim persistence. When durable storage returns, verify the digest, import the anchor once, create a migration event, and resume append-only history.
