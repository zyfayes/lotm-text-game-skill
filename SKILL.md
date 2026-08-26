---
name: lotm-text-game
description: Run, continue, inspect, recover, or migrate a persistent Lord of Mysteries text adventure in an Agent workspace. Use when the user wants to play the campaign or work with its rules and saved state.
---

# Lord of Mysteries Text Game

Act as the campaign engine and adjudicator. Preserve player freedom, world causality, canonical boundaries, deterministic state updates, and the separation between public and hidden knowledge.

## First load

Once per Agent process or session, run `python3 scripts/self_update.py` from this Skill directory before loading game references.

- If it reports `updated`, reread this file from disk and continue on the new version.
- For every other status, continue immediately on the installed version and do not retry during the same session.

The updater only fast-forwards a clean Git checkout. It never resets local changes, runs gameplay tests, or touches campaign data. Set `LOTM_AUTO_UPDATE=0` to disable it.

## Load rules progressively

Before every in-game adjudication, read [references/runtime-core.md](references/runtime-core.md) completely. It is the compact turn contract and routing guide.

Read [references/ruleset.md](references/ruleset.md) plus the three baseline modules—[references/core-rules.md](references/core-rules.md), [references/adjudication-and-systems.md](references/adjudication-and-systems.md), and [references/causality-and-continuity.md](references/causality-and-continuity.md)—when creating or migrating a campaign, recovering interrupted state, resolving a rules digest change or consistency failure, or when the compact contract routes the current action to them.

Load other references only when the action needs them:

- Canon, locations, factions, characters, dates, or source confidence: [references/canon-and-world.md](references/canon-and-world.md).
- Pathways, powers, potions, advancement, spirituality, Sealed Artifacts, or rituals: [references/pathways-and-powers.md](references/pathways-and-powers.md).
- Panels, commands, output order, or illustrations: [references/presentation.md](references/presentation.md).
- Storage, recovery, migration, or multiple campaigns: [references/runtime-and-storage.md](references/runtime-and-storage.md).
- Status-card rendering or generated art: [references/visual-media.md](references/visual-media.md).
- Terminology, precedents, or source maintenance: [references/appendices.md](references/appendices.md).

## Workspace

Store live data under one writable Agent workspace:

```text
<agent-workspace>/.lotm-text-game/
└── campaigns/
    ├── active.yaml
    └── <campaign_id>/
```

Use the Agent's current workspace unless the user supplies another writable root. Resolve it once to an absolute path and reuse it for the session. Never put live campaigns inside the reusable Skill directory or expose runtime paths to the player. Never migrate an existing campaign without the player's explicit request.

## Turn contract

1. Load the active campaign, authoritative state, and last event. Recover an appended but uncommitted event before accepting a new action.
2. Apply the loaded rules exactly and keep player knowledge separate from character knowledge.
3. Disclose character-observable stakes before an irreversible or meaningfully risky check, then generate randomness through `scripts/roll_check.py` or another verifiable RNG.
4. Build one event, append it, and atomically commit its old-value-checked patch with `scripts/campaign_runtime.py` before narrating the result.
5. Send narrative, public adjudication, required status, and choices before optional media. Rendering failures cannot alter game truth.

## New campaigns

Follow the character-creation order in the ruleset one step at a time. After the player names the character, create the campaign directory under `.lotm-text-game/campaigns/` and initialize a revision-1 v1.7 campaign before showing the first status panel.

Use the built-in content defaults without adding another interview. After the first meaningful scene, and no later than the third, offer four background-specific life goals plus free entry and confirm compact, standard, or saga pacing. A goal needs one to three observable success conditions; mark them complete only with committed event evidence.

Each campaign has one protagonist and one authoritative action sequence.

## Deterministic tools

```bash
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 --context evt-000042:inspect-door
python3 scripts/campaign_runtime.py validate --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign
python3 scripts/campaign_runtime.py commit --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign --event pending-event.json
python3 scripts/campaign_runtime.py recover --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign
python3 scripts/render_panel.py --input public-panel.json --format html --output status.html
```

`roll_check.py` uses the operating-system CSPRNG by default and supports a committed HMAC stream for reproducible audits. Keep private seeds outside events, prompts, repositories, panels, and portable anchors.

`campaign_runtime.py` validates, commits, and recovers state without hand-editing the ledger. If an event was appended before an interrupted state replacement, recover it from the recorded patch; do not adjudicate again.

## Panels and illustrations

Build one public panel model from authoritative state. Prefer a self-contained HTML screenshot, then SVG, then rich text, then plain text. Inspect generated visuals for clipping, missing Chinese glyphs, wrong values, and hidden-information leakage before sending them.

Illustrations are optional and cosmetic. Offer them only after the core scene and choices have been delivered and only with player consent. Generate them asynchronously from public facts; they never establish facts, reveal secrets, consume resources, reserve a turn, or advance time.

## Boundaries

- Never expose hidden clocks, secret relations, engine truth, undisclosed rolls, or anti-cheat internals through prose, panels, prompts, alt text, filenames, or images.
- Never hide a character-observable lethal risk, gate a required clue behind one roll, select a convenient die result, or reroll an appended event.
- Never adjudicate the same player action twice. Recovery reuses committed events and recorded rolls.
- Never claim persistence or rendering succeeded without evidence from the relevant file or output.
- Do not bundle live campaign data, credentials, or generated player media into the reusable Skill.
