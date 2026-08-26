# Transport adapters

Read this reference when delivering the game through Telegram or another IM platform.

The engine commits one transport-neutral event. The adapter turns that committed event into platform messages and buttons. Presentation retries never invoke adjudication again.

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
    alt: "..."
  - kind: choices
    body: "..."
    buttons: []
optional_media_offer:
  scene_event_id: evt-000128
```

Split messages only at semantic boundaries. Keep the timestamp with narrative, the formula summary with adjudication, and every option with its number.

## Telegram adapter

Recommended sequence:

1. Send narrative and public adjudication with `sendMessage` using Telegram HTML entities.
2. If a panel is required, send its PNG, JPEG, or WebP through `sendPhoto` with a short caption.
3. Send choices with an Inline Keyboard. Keep the constant free-action instruction in text.
4. If the player approved a scene illustration, deliver it as a separate photo tied to the originating event.

Use compact button payloads:

```text
g:<campaign-short-id>:<event-seq>:<choice>
```

The server resolves the full action from committed state. Never put secrets, prose, hidden data, or mutable state in callback data.

Deduplicate all inbound updates using Telegram `update_id`. Deduplicate callback presses using the callback query identifier and the originating event sequence. Always answer callback queries promptly, while long adjudication and media work continue in the job system.

For forum topics include `message_thread_id` in the campaign scope. In groups, reject actions from users outside the configured player scope unless shared-party mode explicitly permits them.

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
- Message editing unavailable: send a correction message; never silently rewrite a committed result.
- Strict message limits: split narrative at paragraph boundaries and keep choices in the final message.

## Delivery truth

Only mark an outbox item delivered after the platform returns a success identifier. Store reusable platform file identifiers as transport cache, never as game inventory. If a send call times out after possible success, reconcile through the platform or retry with an idempotency strategy; do not generate a second game event.
