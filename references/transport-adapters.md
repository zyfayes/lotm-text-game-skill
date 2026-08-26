# Transport adapters

Read this reference when delivering the game through Telegram or another IM platform.

The engine commits one transport-neutral event. The adapter turns that committed event into platform messages and buttons. Presentation retries never invoke adjudication again.

When local Python exists, `scripts/transport_contract.py` can validate and adapt the generic envelope for a capability profile. It is a deterministic delivery planner, not an adjudicator.

## Capability profile

Detect or configure:

```yaml
platform: telegram
supports_raster_image: true
supports_inline_svg: false
supports_html_view: false
supports_rich_text: true
supports_buttons: true
supports_message_edit: true
max_text_chars: 4096
max_caption_chars: 1024
button_payload_bytes: 64
```

Treat values as deployment configuration and verify them against current platform documentation.

## Generic output envelope

For each committed turn, build:

```yaml
event_id: evt-000128
state_revision: 128
messages:
  - kind: narrative
    body: "..."
  - kind: adjudication
    body: "..."
  - kind: status_media
    media_ref: "..."
    caption: "..."
    alt: "..."
    fallback_text: "..."
  - kind: choices
    body: "..."
    buttons: []
optional_media_offer:
  scene_event_id: evt-000128
  execution: async
  blocks_turn: false
```

An optional-media offer is valid only with `execution: async` and `blocks_turn: false`. The adapter must reject a synchronous or turn-blocking illustration configuration rather than silently delaying play.

Split messages only at semantic boundaries. Keep the timestamp with narrative, the formula summary with adjudication, and every option with its number.

## Telegram adapter

Recommended sequence:

1. Send narrative and public adjudication with `sendMessage` using Telegram HTML entities.
2. If a panel is required and already rendered, send its PNG, JPEG, or WebP through `sendPhoto` with a short caption. If rendering or upload is delayed, send the same revision's required status summary as text and enqueue the image separately.
3. Send choices with an Inline Keyboard. Keep the constant free-action instruction in text.
4. If the player approved a scene illustration, deliver it as a separate photo tied to the originating event.

Use compact button payloads:

```text
g:<campaign-short-id>:<event-seq>:<choice>
```

The server resolves the full action from committed state. Never put secrets, prose, hidden data, or mutable state in callback data.

Deduplicate all inbound updates using Telegram `update_id`. Deduplicate callback presses using the callback query identifier and the originating event sequence. Always answer callback queries promptly, while long adjudication and media work continue in the job system. AI illustration work is always asynchronous and cannot hold the campaign lock or delay acceptance of the next action.

For forum topics include `message_thread_id` in the campaign scope. In groups, reject actions from users outside the configured controller scope.

v1.7 has no shared-party rules. A group may share the view, but only the configured controller can create actions; other members are spectators whose messages do not enter the game transaction.

Telegram reference points:

- https://core.telegram.org/bots/api#update
- https://core.telegram.org/bots/api#sendmessage
- https://core.telegram.org/bots/api#sendphoto
- https://core.telegram.org/bots/api#inlinekeyboardbutton
- https://core.telegram.org/bots/api#setwebhook

## Other IM platforms

Map the same envelope by capability:

- Rich embeds available: put short state fields in the embed and attach the raster card when useful.
- Image attachment available: send the raster card and concise alt text.
- Buttons unavailable: send numbered choices and accept a number or free text.
- Message editing unavailable: send a correction message; never silently rewrite a committed result. A correction may name `target_message_id`; the planner edits only when the platform supports it and the correction fits one message.
- Strict message limits: split narrative at paragraph boundaries, deliver choices afterward, and keep every option number attached to its full text.

## Portable degradation contract

- No filesystem: do not claim durable persistence; keep the complete digest-protected portable anchor in a private channel and import it before the next adjudication.
- No raster image: replace status media with the same revision's rich-text summary or alt fallback. Do not omit required state information.
- No buttons: keep numbered choices in text and accept a number or free action. Button absence cannot remove free-form play.
- Short message limit: split at semantic or paragraph boundaries. Never separate an option number from its text, and never exceed the configured limit.
- Duplicate webhook or callback: return the stored event or delivery result for that ingress identifier. Do not call the game engine again.
- Media timeout: leave the outbox item pending or mark it retryable. If required status media is delayed, deliver its same-revision text fallback; optional illustrations remain asynchronous. The committed event, state revision, roll, and world time remain unchanged.
- Multiple sessions: resolve the full scope key before the active campaign. Two chats or topics with the same actor must not share an active pointer unless explicitly configured.

Run the bundled contract tests before deploying a new adapter:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/transport_contract.py plan --envelope turn-envelope.json --capabilities transport-capabilities.json
```

## Delivery truth

Only mark an outbox item delivered after the platform returns a success identifier. Store reusable platform file identifiers as transport cache, never as game inventory. If a send call times out after possible success, reconcile through the platform or retry with an idempotency strategy; do not generate a second game event.
