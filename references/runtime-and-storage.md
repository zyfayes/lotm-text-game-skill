# Runtime and storage

Read this reference when creating, opening, recovering, exporting, importing, or switching campaigns. Transaction order and continuity rules remain authoritative in [causality-and-continuity.md](causality-and-continuity.md).

## Workspace

Use one writable runtime directory:

```text
<agent-workspace>/.lotm-text-game/
├── campaigns/
│   ├── active.yaml
│   └── <campaign_id>/
└── private/
```

The current Agent workspace is the default. The user may supply another writable workspace. Resolve the selected path once to an absolute path and reuse it for the session.

Keep runtime data outside the reusable Skill directory. Absolute paths are runtime metadata and never enter campaign state, events, anchors, prompts, panels, or player-visible output.

## Campaign files

Each campaign directory contains:

```text
<campaign_id>/
├── state.yaml
├── events.jsonl
├── journal.md
├── canon-deviations.md
├── latest-anchor.md
└── media/
```

- `active.yaml` points to the active campaign and latest known revision.
- `state.yaml` is the current authoritative state.
- `events.jsonl` is the append-only event history.
- `journal.md` contains only facts the character has experienced or confirmed.
- `canon-deviations.md` records changes around canon anchors.
- `latest-anchor.md` is a portable checkpoint, never a save point for rerolling history.
- `media/` contains presentation artifacts and is never authoritative state.
- `private/` may contain RNG seeds and other engine-only material. Never export or display it.

New campaigns use [campaign-state.schema.json](campaign-state.schema.json), [campaign-event.schema.json](campaign-event.schema.json), and [portable-anchor.schema.json](portable-anchor.schema.json). Archived v1.6 campaigns use their matching `.v1.6.schema.json` contracts. v1.2–v1.5 ledgers remain read-only until the player explicitly requests migration.

## File operations

Use the bundled runtime instead of hand-editing authoritative records:

```bash
python3 scripts/campaign_runtime.py validate --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign
python3 scripts/campaign_runtime.py commit --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign --event pending-event.json
python3 scripts/campaign_runtime.py recover --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign
python3 scripts/campaign_runtime.py export-anchor --campaign-dir /absolute/workspace/.lotm-text-game/campaigns/example-campaign --output portable-anchor.json
```

The helper writes canonical JSON text to `state.yaml`; JSON is valid YAML 1.2. It also reads ordinary YAML when PyYAML is installed.

Before a new action, validate the current state and recover any appended event not yet reflected in `state.yaml`. A revision conflict stops the commit. Reload current state instead of overwriting it. A recovered event reuses its recorded roll and patch.

## Private randomness

The default roll mode uses the operating-system CSPRNG. Reproducible audits may use a private campaign seed stored under `.lotm-text-game/private/`:

```bash
python3 scripts/roll_check.py init-seed --output /absolute/workspace/.lotm-text-game/private/example-campaign.seed
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 \
  --context evt-000042:inspect-door --seed-file /absolute/workspace/.lotm-text-game/private/example-campaign.seed --counter 17
```

Record the seed commitment, counter, context, raw value, and adjudication. Never record, export, or expose the private seed.

## Migration

Verify a portable anchor before importing it. When it becomes authoritative in another workspace, append the required migration event and continue the same event history. Anchors contain hidden state and must remain private.
