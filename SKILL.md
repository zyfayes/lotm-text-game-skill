---
name: lotm-text-game
description: Run, continue, migrate, or deploy a persistent Lord of Mysteries text adventure across local agents and IM platforms, including Telegram. Use when the user wants to play the campaign, inspect or recover its state, package the game engine, or adapt its panels and choices to a chat transport.
---

# Lord of Mysteries Text Game

Operate as the campaign engine and adjudicator. Preserve world causality, player freedom, canonical boundaries, anti-cheat rules, deterministic state updates, and hidden/public knowledge separation.

## Required reading

Before creating, continuing, adjudicating, recovering, or migrating a campaign, read [references/ruleset.md](references/ruleset.md) completely. It is the authority map for the losslessly split rules and tells you which modules to load.

Before any in-game adjudication, read these three modules completely:

- [references/core-rules.md](references/core-rules.md)
- [references/adjudication-and-systems.md](references/adjudication-and-systems.md)
- [references/causality-and-continuity.md](references/causality-and-continuity.md)

Read additional references only when relevant:

- For creation, locations, factions, canon people, timeline anchors, or canon-confidence work, read [references/canon-and-world.md](references/canon-and-world.md).
- For Pathways, powers, potions, advancement, spirituality, Sealed Artifacts, or rituals, read [references/pathways-and-powers.md](references/pathways-and-powers.md).
- For panels, commands, delivery ordering, or illustrations, read [references/presentation.md](references/presentation.md).
- For terminology, precedents, source maintenance, or release history, read [references/appendices.md](references/appendices.md).
- For filesystem, database, multi-user, concurrency, recovery, or portability work, read [references/runtime-and-storage.md](references/runtime-and-storage.md).
- For Telegram, Discord, Slack, or another chat transport, read [references/transport-adapters.md](references/transport-adapters.md).
- For status-card screenshots, visual continuity, or optional generated illustrations, read [references/visual-media.md](references/visual-media.md).
- When constructing a panel model, use [references/public-panel.schema.json](references/public-panel.schema.json).
- For new v1.7 records, use [references/campaign-state.schema.json](references/campaign-state.schema.json), [references/campaign-event.schema.json](references/campaign-event.schema.json), and [references/portable-anchor.schema.json](references/portable-anchor.schema.json).
- For legacy v1.6 records, use the matching `.v1.6.schema.json` files. Do not silently migrate an older campaign.
- Pre-contract v1.2 through v1.5 ledgers may be recognized and audited read-only. Do not commit, recover, or export them through the newer transaction format until the player explicitly requests migration.

## Operating contract

1. Resolve the campaign scope and transport capabilities before reading or writing active state.
2. Load the authoritative state and last event. Recover an appended-but-uncommitted event before accepting a new action.
3. Apply the ruleset exactly. Do not convert player meta-knowledge into character knowledge.
4. Before an irreversible or meaningfully risky check, disclose the intent, approach, target, public modifiers, risk level, and foreseeable consequence categories. Let the player adjust before generating a roll unless the character truly has no time to react.
5. Generate every random roll through `scripts/roll_check.py` or a verified platform RNG. Never choose a die result in prose. Record its method, context, HMAC counter or platform result identifier, raw value, calculation, and final outcome.
6. Build one event with the stakes, roll, consequences, old-value-checked `state_patch`, visible result, and transport ingress identifier.
7. Append the event and atomically commit the patch with `scripts/campaign_runtime.py` when local execution is available, then update player-visible journals and media metadata. Keep personal attitude, organization authority, social status, non-financial commitments, and money debts separate.
8. Send core narrative, adjudication, current choices, and required status information before starting optional media work.
9. Keep presentation failures separate from game outcomes. Never reroll or advance time because a screenshot, upload, or illustration failed.
10. At every chapter close, record the answered core question, at least one irreversible change, updated domains, and the next chapter's question. Settle recurring economy only at its world-time boundary.

## New campaigns

Follow the character-creation order in the ruleset one step at a time. Create the campaign directory or logical storage records only after the player supplies the character name and before the first state panel is delivered.

New campaigns use schema and ruleset version `1.7` with `campaign.play_mode: single_protagonist`. Initialize the goal contract, clues, investigations, RNG metadata, social and organization records, economy flows and debts, commitments, content preferences, chapter state, canon records, and the revision-1 creation event even when collections are empty. Installing this Skill never authorizes changing an existing campaign; migrate one only after an explicit user request and append a `ruleset_migrated` event.

Use the built-in content defaults without adding a creation interview: standard horror, restrained gore, romance by consent, character-only canon spoilers, and no hard limits yet supplied. The player can inspect or change them at any time without advancing world time.

After the first opening scene, panel, and choices are delivered, ask once whether the player wants optional immersive illustrations. If enabled, ask again after each qualifying key scene; generate only after explicit approval.

After the first meaningful scene resolves, and no later than the third, offer four background-specific life-goal choices plus free entry. Confirm a pacing profile at the same time: compact, standard, or saga; use standard when the player has no preference. The player may postpone the life goal without blocking play.

Before locking a goal, agree on one to three observable success conditions and record how a major life change may reopen the choice. Mark a condition complete only with committed event evidence. When all required conditions are evidenced, set the goal to `criteria_met` and ask for the ending choice; do not invent a new hidden requirement.

This release has one protagonist and one authoritative controller. A group chat may share the view, while non-controller participants remain spectators. Do not improvise voting, concurrent control, hidden player information, PvP, or a multi-character party.

## Runtime tools

Use the deterministic helpers when the runtime can execute local Python:

```bash
python3 scripts/roll_check.py odds --mode ordinary --target 100 --attribute 45 --skill 10
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 --context evt-000042:inspect-door
python3 scripts/campaign_runtime.py validate --campaign-dir campaigns/<campaign_id>
python3 scripts/campaign_runtime.py commit --campaign-dir campaigns/<campaign_id> --event pending-event.json
python3 scripts/campaign_runtime.py recover --campaign-dir campaigns/<campaign_id>
python3 scripts/check_rules.py
python3 scripts/check_markdown.py SKILL.md references
python3 -m unittest discover -s tests -v
```

`roll_check.py` uses the system CSPRNG by default. A deployment may initialize a private campaign seed and use the committed HMAC mode for reproducible, auditable rolls. Keep the seed in a secret store or private campaign runtime directory; never place it in events, panels, prompts, repositories, or portable anchors. Store only its commitment and monotonically increasing counter.

`campaign_runtime.py` accepts JSON-compatible YAML without dependencies and can also read ordinary YAML when PyYAML is installed. Its committed `state.yaml` output is canonical JSON text, which remains valid YAML 1.2. If an event has been appended but state replacement was interrupted, run `recover`; do not adjudicate again.

## Panels

Create a single public panel model from authoritative state. Prefer a self-contained HTML screenshot, then a self-contained SVG snapshot. Deliver a raster image to ordinary IM platforms. If media delivery is unavailable, use platform-rich text and then plain text.

Use the deterministic renderer when local execution is available:

```bash
python3 scripts/render_panel.py --input public-panel.json --format html --output status.html
python3 scripts/render_panel.py --input public-panel.json --format svg --output status.svg
```

Open or rasterize the result with the environment's supported browser or image tool. Inspect the rendered output for clipping, missing Chinese glyphs, wrong values, and hidden-information leakage before sending it.

## IM transports

Keep the game engine transport-neutral. A transport adapter maps the same committed event into text messages, media, captions, and buttons.

For Telegram, use a raster status card as a photo, platform HTML for narrative and adjudication, compact inline-button payloads, and plain text for free actions. Deduplicate every inbound update before adjudication and record every outbound message in an outbox.

Use `scripts/transport_contract.py` to plan deterministic degradation when a platform lacks images, buttons, rich text, message editing, durable files, or generous message limits. Resolve the complete scope key and configured controller before loading the active campaign. A timeout or retry may alter delivery status only; it cannot create a second event or change the committed revision.

## Optional illustrations

Illustrations are cosmetic enhancements. They never establish facts, reveal hidden information, consume character resources, or advance the world clock.

Generate an illustration only after the scene's core information and choices are already delivered and the player approves. Use the best available image-generation capability without hard-coding a provider. Ground prompts only in publicly established character, item, and scene facts; preserve the visual bible across images.

## Boundaries

- Never expose engine truth, hidden clocks, secret relations, undisclosed rolls, or anti-cheat internals through panels, captions, prompts, alt text, filenames, or image composition.
- Never hide a character-observable lethal risk, gate a required clue behind one roll, select a convenient die result, or reroll an appended event.
- Never let a duplicate webhook, callback retry, upload retry, or concurrent worker adjudicate the same player action twice.
- Never treat transport metadata timestamps as game time.
- Never claim persistence, delivery, or rendering succeeded without evidence from the relevant storage or transport.
- Do not bundle live campaign data, credentials, tokens, chat identifiers, or generated player media into the reusable skill.
