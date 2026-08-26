# Runtime and storage contract

Read this reference when the campaign runs outside a single local workspace, when multiple campaigns or users exist, or when recovery, migration, concurrency, or database storage matters.

The full game semantics and file responsibilities remain defined by [ruleset.md](ruleset.md). This document maps those logical records to portable runtimes.

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

Local files, SQLite, PostgreSQL, object storage, or an Agent platform database may implement the records. Storage choice cannot change adjudication.

When the ruleset names `state.yaml`, `events.jsonl`, `journal.md`, `canon-deviations.md`, `latest-anchor.md`, or `active.yaml`, a service runtime may satisfy that rule through the corresponding logical record below. The filename expresses record semantics, not a mandatory physical storage engine.

## Campaign scope

Use a stable scope key before resolving the active campaign:

~~~text
<platform>:<agent-or-bot-id>:<conversation-id>:<thread-id-or-0>:<player-scope>
~~~

Examples:

~~~text
local:codex:example-project:0:single
telegram:example-bot:example-group:example-thread:shared
telegram:example-bot:example-user-chat:0:example-user
~~~

Private chats normally use one campaign per chat. Group and forum chats must explicitly choose either a shared campaign or one campaign per player. Never use one global active pointer for an entire bot service.

## Local filesystem profile

For a single-player workspace, preserve the ruleset layout:

~~~text
campaigns/
├── active.yaml
└── <campaign_id>/
    ├── state.yaml
    ├── events.jsonl
    ├── journal.md
    ├── canon-deviations.md
    └── latest-anchor.md
~~~

Generated panels and illustrations belong under a campaign media directory or external media store and must not be treated as authoritative state.

## Multi-tenant service profile

A service may map the same records to tables or namespaced objects:

~~~text
campaign_scopes(scope_key, active_campaign_id, state_revision)
campaign_states(campaign_id, state_revision, state_json, updated_at)
campaign_events(campaign_id, event_id, ingress_id, payload_json, created_at)
campaign_documents(campaign_id, kind, revision, body)
processed_ingress(scope_key, ingress_id, result_event_id)
transport_outbox(outbox_id, campaign_id, event_id, payload, status, platform_message_id)
campaign_media(media_id, campaign_id, event_id, kind, public_facts_hash, platform_file_id)
~~~

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
5. Adjudicate once and produce one primary event.
6. Append the complete event.
7. Compare-and-swap state from the expected revision to the next revision.
8. Update player-visible documents.
9. Create transport outbox records in the same transaction when possible.
10. Commit before sending messages.
11. Deliver outbox items idempotently and record platform message identifiers.

If delivery fails after commit, retry delivery from the outbox. Never re-adjudicate the action.

## Ingress metadata

Each externally triggered action records enough data to deduplicate and audit it:

~~~yaml
transport:
  platform: telegram
  scope_key: "telegram:example-bot:example-user-chat:0:example-user"
  ingress_id: "update:example-update"
  conversation_id: "example-user-chat"
  thread_id: null
  actor_id: "example-user"
  message_id: "example-message"
  callback_id: null
~~~

Button callbacks use the callback query identifier as an additional ingress identifier. An edited message does not silently replace an already adjudicated action; treat it as a new request to clarify or correct.

## Concurrency and recovery

- Serialize turns per campaign scope, not globally across the service.
- Reject or retry compare-and-swap conflicts after reloading state; never overwrite a newer revision.
- Store rolls inside the event before narrative delivery.
- Recover appended events from their recorded deltas without rerolling.
- Keep real timestamps separate from world time.
- Media jobs may run concurrently after the event commits because they cannot mutate game truth.

## Secrets and hidden state

Transport tokens, database credentials, signing secrets, and webhook secrets live in the deployment secret store. They never enter campaign state, events, prompts, screenshots, logs intended for players, or the reusable skill package.

Hidden engine records must be accessible to the adjudicator and inaccessible to player-facing renderers. Treat file separation as organization; enforce actual access control in service deployments.

## Portable fallback

If durable storage is unavailable, emit the complete latest anchor required by the ruleset and mark the campaign as degraded. Do not claim persistence. When durable storage returns, import the anchor once, create a migration event, and resume append-only history.
