# LOTM Text Game Skill

**English** · [简体中文](README_CN.md)

A persistent, consequence-driven text adventure inspired by *Lord of Mysteries*, built as a portable Agent Skill.

Play an ordinary person living in Tingen on June 28, 1349—the same world and time in which Klein Moretti has just awakened. Choose any plausible life, pursue any faction or Pathway, interfere with familiar events, or ignore them entirely. The world keeps moving, and every meaningful action can bend its future.

This is a game engine, not a scripted story. It combines open-ended role-play with explicit adjudication, durable campaign state, canon-aware knowledge boundaries, deterministic status panels, and transport contracts for local agents and IM platforms.

## Why it is fun

| System | What it adds to play |
|---|---|
| Free-form action | Suggested choices never lock the player into a menu. Any plausible in-world action can be attempted. |
| A living timeline | Factions, threats, and major events continue to develop even when the player looks elsewhere. |
| Real consequences | Money, injuries, suspicion, relationships, corruption, and missed timing all persist. |
| Fair risk and failure | Irreversible checks disclose foreseeable stakes first; failure changes the situation and leaves a new way forward. |
| Solvable mysteries | Required conclusions keep independent clue routes, while evidence carries source, confidence, and verification state. |
| Sequence progression | Potions, acting, spirituality, rituals, ingredients, and loss-of-control risk form one connected advancement loop. |
| Butterfly effects | Interventions accumulate causal weight and can redirect major story anchors without turning canon characters into puppets. |
| No save-scumming | Rolls and consequences are committed once. Recovery restores interrupted writes; it never rerolls history. |
| Auditable randomness | Checks use a system CSPRNG, committed HMAC stream, or verified platform RNG and store the raw roll, context, counter or platform receipt, and adjudication. |
| Three difficulty modes | Play a fate-favored adventure, a grounded ordinary life, or a hostile survival campaign. |
| Optional illustrations | Important people, objects, and scenes can receive generated artwork after the core turn is complete and the player agrees. |

## Winning, losing, and campaign length

After the first meaningful scene, the Agent offers four life goals tailored to the character's background and public story hooks, plus a free-entry option. Typical directions include freedom, truth or revenge, Beyonder mastery, status or belonging, and protecting someone or changing a fate. Before a goal is locked, the player confirms one to three observable success conditions. Every completed condition points to committed event evidence, preventing the ending threshold from drifting later.

| Outcome | Meaning |
|---|---|
| Victory | The life goal is fulfilled and the player chooses to conclude the campaign. |
| Unfinished | The player retires before completing the current life goal. |
| Defeat | The character irreversibly dies, loses control, is assimilated, or permanently loses agency with no plausible in-world recovery. |

Completing a goal opens an ending choice; it does not force the campaign to stop. The player may archive that goal and choose another. Temporary failure, imprisonment, debt, injury, or a broken relationship remains part of play rather than an automatic defeat.

Every ending also receives an independent legacy scale—Mortal, Beyonder, Legendary, or Mythic—based on causal impact rather than Sequence alone. A mortal can win and leave a legend; a powerful Beyonder can fail.

| Pacing profile | Expected shape |
|---|---|
| Compact | About 12–20 meaningful scenes across 3–4 chapters |
| Standard | About 30–60 meaningful scenes across 5–8 chapters; the default |
| Saga | 80+ meaningful scenes for multi-city, multi-faction, or high-Sequence play |

These are visible expectations, not hard turn limits. A meaningful scene must contain a real choice, discovery, consequence, relationship change, or world advance. If two consecutive scenes produce none of those, the Agent must compress the transition or move to the next effective node. Players can change pacing at any time without changing difficulty or advancing the world clock.

## Core design

The engine separates game truth from presentation. An HTML failure, Telegram retry, or image-generation timeout can never alter a roll or advance the clock.

```mermaid
flowchart TD
    U[Player] --> T[Local Agent or IM Transport]
    T --> A[Agent running SKILL.md]
    A --> R[Ruleset and adjudication]
    R --> D{Check required?}
    D -->|Yes| G[Auditable d100 RNG]
    D -->|No| E[Append one immutable event]
    G --> E
    E --> S[Commit authoritative state]
    S --> J[Journal and portable anchor]
    S --> P[Public panel model]
    P --> H[HTML or SVG renderer]
    H --> I[PNG / JPEG / WebP]
    P --> F[Rich-text or plain-text fallback]
```

| Layer | Responsibility | Main files |
|---|---|---|
| Agent contract | Loads the correct rules and preserves turn order | `SKILL.md` |
| Game semantics | World, character creation, fair stakes, clue closure, checks, advancement, causality, and endings | `references/ruleset.md` |
| Persistence | Campaign scoping, append-only events, atomic state, concurrency, and recovery | `references/runtime-and-storage.md` |
| Transport | Telegram and generic IM delivery, deduplication, buttons, and outbox behavior | `references/transport-adapters.md` |
| Presentation | Public-data boundaries, mobile status cards, semantic color, and illustration consent | `references/visual-media.md` |
| Deterministic UI | Validates one public model and renders self-contained HTML or SVG | `scripts/render_panel.py` |
| Runtime integrity | Generates auditable checks and validates, commits, or recovers state patches | `scripts/roll_check.py`, `scripts/campaign_runtime.py` |

## Installation

Clone the repository directly into your Codex skills directory:

```bash
git clone https://github.com/zyfayes/lotm-text-game-skill.git \
  ~/.codex/skills/lotm-text-game
```

Restart or refresh the Agent, then invoke:

```text
Use $lotm-text-game to start a new game.
```

Other Agent runtimes that support directory-based skills can load the root `SKILL.md` and preserve the same relative file structure.

## What happens when a campaign starts

1. The player chooses a difficulty.
2. The player chooses a gender.
3. The Agent generates four fresh character backgrounds plus a custom option.
4. The player names the protagonist.
5. The engine creates the durable campaign ledger and immediately renders the first status panel.
6. The opening scene begins with free-form actions and suggested choices.
7. After the first meaningful scene, the player chooses or writes a life goal and confirms the campaign pacing.

Campaigns start with an ordinary person or, for a balanced custom background, at most a Sequence 9 Beyonder with a real cost attached.

New campaigns use the v1.6 state and event contracts. Installing a newer Skill never rewrites an existing campaign automatically; migration requires an explicit request and an appended migration event.

## Campaign persistence

For a local single-player campaign, the engine maintains:

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

`state.yaml` is the latest authoritative state. `events.jsonl` is an append-only audit trail. The journal contains only facts the character has experienced or confirmed. Hidden world state and character knowledge remain separate.

The v1.6 runtime records goal evidence, clues and investigations, public stakes, RNG provenance, consequences, and old-value-checked state patches. Local agents can validate or recover a campaign with:

```bash
python3 scripts/campaign_runtime.py validate --campaign-dir campaigns/<campaign_id>
python3 scripts/campaign_runtime.py recover --campaign-dir campaigns/<campaign_id>
```

The check helper can inspect calibrated odds or generate a real roll:

```bash
python3 scripts/roll_check.py odds --mode ordinary --target 100 --attribute 45 --skill 10
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 \
  --context evt-000042:inspect-door
```

Service deployments may map the same records to SQLite, PostgreSQL, or object storage, but must preserve version checks, idempotency, transaction order, and recovery semantics.

## Rendering status panels

The renderer uses only the Python standard library:

```bash
python3 scripts/render_panel.py \
  --input assets/panel-example.json \
  --format html \
  --output status.html

python3 scripts/render_panel.py \
  --input assets/panel-example.json \
  --format svg \
  --output status.svg
```

The generated HTML and SVG are self-contained. For Telegram, Discord, and similar chat platforms, rasterize them to PNG, JPEG, or WebP before delivery. If visual rendering fails, the engine falls back to platform-rich text and then plain text without changing campaign state.

The UI does not use a universal MMO-style rarity ladder. Sealed Artifact grades, event danger, Sequence level, formula confidence, and publicly confirmed item types remain separate concepts. Color supports those known meanings but never performs a hidden appraisal.

## Repository structure

```text
.
├── SKILL.md
├── agents/
│   └── openai.yaml
├── assets/
│   ├── dossier-masthead-engraving.png
│   ├── icon.svg
│   ├── panel-example.json
│   └── panel-example.png
├── references/
│   ├── public-panel.schema.json
│   ├── campaign-state.schema.json
│   ├── campaign-event.schema.json
│   ├── portable-anchor.schema.json
│   ├── ruleset.md
│   ├── runtime-and-storage.md
│   ├── transport-adapters.md
│   └── visual-media.md
├── scripts/
│   ├── campaign_runtime.py
│   ├── roll_check.py
│   └── render_panel.py
└── tests/
    └── test_p0_runtime.py
```

Run the standard-library regression suite with:

```bash
python3 -m unittest discover -s tests -v
```

## Safety and privacy

- Live campaign data, player media, chat identifiers, credentials, and bot tokens do not belong in the reusable Skill.
- Player-visible panels and image prompts may contain only publicly established facts.
- Duplicate webhooks, callback retries, or failed uploads must never adjudicate the same action twice.
- Optional illustrations are cosmetic. They cannot create items, reveal secrets, consume resources, or advance time.

## Disclaimer

This is an unofficial, non-commercial fan project. It is not affiliated with or endorsed by China Literature, Qidian, the author Cuttlefish That Loves Diving, or any official license holder. Names, characters, settings, and other elements originating from *Lord of Mysteries* remain the property of their respective rights holders.

The worldbuilding, game rules, and presentation also draw inspiration from ideas shared online by readers, tabletop role-playing players, and text-game enthusiasts. This repository is provided solely for learning and community discussion.

The MIT License applies only to original software, operating protocols, and interface implementation for which the repository author has authority to grant permission. It does not grant rights to third-party intellectual property. Users are responsible for ensuring that their deployment, distribution, and generated content comply with applicable law and platform rules.
