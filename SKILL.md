---
name: lotm-text-game
description: Run, continue, migrate, or deploy a persistent Lord of Mysteries text adventure across local agents and IM platforms, including Telegram. Use when the user wants to play the campaign, inspect or recover its state, package the game engine, or adapt its panels and choices to a chat transport.
---

# Lord of Mysteries Text Game

Operate as the campaign engine and adjudicator. Preserve world causality, player freedom, canonical boundaries, anti-cheat rules, deterministic state updates, and hidden/public knowledge separation.

## Required reading

Before creating, continuing, adjudicating, recovering, or migrating a campaign, read [references/ruleset.md](references/ruleset.md) completely. It is the authority for every game rule and cannot be summarized away.

Read additional references only when relevant:

- For filesystem, database, multi-user, concurrency, recovery, or portability work, read [references/runtime-and-storage.md](references/runtime-and-storage.md).
- For Telegram, Discord, Slack, or another chat transport, read [references/transport-adapters.md](references/transport-adapters.md).
- For status-card screenshots, visual continuity, or optional generated illustrations, read [references/visual-media.md](references/visual-media.md).
- When constructing a panel model, use [references/public-panel.schema.json](references/public-panel.schema.json).

## Operating contract

1. Resolve the campaign scope and transport capabilities before reading or writing active state.
2. Load the authoritative state and last event. Recover an appended-but-uncommitted event before accepting a new action.
3. Apply the ruleset exactly. Do not convert player meta-knowledge into character knowledge.
4. Build one event with the roll, modifiers, consequences, state deltas, visible results, and transport ingress identifier.
5. Append the event, atomically commit state, then update player-visible journals and media metadata.
6. Send core narrative, adjudication, current choices, and required status information before starting optional media work.
7. Keep presentation failures separate from game outcomes. Never reroll or advance time because a screenshot, upload, or illustration failed.

## New campaigns

Follow the character-creation order in the ruleset one step at a time. Create the campaign directory or logical storage records only after the player supplies the character name and before the first state panel is delivered.

After the first opening scene, panel, and choices are delivered, ask once whether the player wants optional immersive illustrations. If enabled, ask again after each qualifying key scene; generate only after explicit approval.

After the first meaningful scene resolves, and no later than the third, offer four background-specific life-goal choices plus free entry. Confirm a pacing profile at the same time: compact, standard, or saga; use standard when the player has no preference. The player may postpone the life goal without blocking play.

## Panels

Create a single public panel model from authoritative state. Prefer a self-contained HTML screenshot, then a self-contained SVG snapshot. Deliver a raster image to ordinary IM platforms. If media delivery is unavailable, use platform-rich text and then plain text.

Use the deterministic renderer when local execution is available:

~~~bash
python3 scripts/render_panel.py --input public-panel.json --format html --output status.html
python3 scripts/render_panel.py --input public-panel.json --format svg --output status.svg
~~~

Open or rasterize the result with the environment's supported browser or image tool. Inspect the rendered output for clipping, missing Chinese glyphs, wrong values, and hidden-information leakage before sending it.

## IM transports

Keep the game engine transport-neutral. A transport adapter maps the same committed event into text messages, media, captions, and buttons.

For Telegram, use a raster status card as a photo, platform HTML for narrative and adjudication, compact inline-button payloads, and plain text for free actions. Deduplicate every inbound update before adjudication and record every outbound message in an outbox.

## Optional illustrations

Illustrations are cosmetic enhancements. They never establish facts, reveal hidden information, consume character resources, or advance the world clock.

Generate an illustration only after the scene's core information and choices are already delivered and the player approves. Use the best available image-generation capability without hard-coding a provider. Ground prompts only in publicly established character, item, and scene facts; preserve the visual bible across images.

## Boundaries

- Never expose engine truth, hidden clocks, secret relations, undisclosed rolls, or anti-cheat internals through panels, captions, prompts, alt text, filenames, or image composition.
- Never let a duplicate webhook, callback retry, upload retry, or concurrent worker adjudicate the same player action twice.
- Never treat transport metadata timestamps as game time.
- Never claim persistence, delivery, or rendering succeeded without evidence from the relevant storage or transport.
- Do not bundle live campaign data, credentials, tokens, chat identifiers, or generated player media into the reusable skill.
