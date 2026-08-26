# Visual panels and immersive illustrations

Read this reference when generating status-card screenshots, character or item art, or key-scene illustrations.

## Visual panel pipeline

1. Build and validate one public panel model against [public-panel.schema.json](public-panel.schema.json).
2. Generate self-contained HTML when browser screenshot capability exists; otherwise generate self-contained SVG.
3. Render or rasterize to a platform-safe image.
4. Inspect the actual image for clipping, Chinese glyphs, wrong values, unreadable type, and hidden-information leakage.
5. Send the image through the transport adapter with concise alt text.

The panel is deterministic UI. Do not use an image-generation model to draw numeric state cards because it may alter text and values. Generated art may be used only as a non-semantic decorative layer behind deterministic text; removing that layer must not remove or change any game information.

## Visual direction

- Palette: fog-wine `#6d1f2e`, oxblood `#3a0d16`, old gold `#9a6b1f`, parchment `#f8f2ec`, ink `#292421`, mist `#a7aaa5`.
- Typography: restrained Chinese serif display face, highly legible Chinese body face, tabular or monospaced numerals. At final mobile display size, body text must remain at least about 14 CSS pixels and critical values at least about 24 CSS pixels.
- Signature: one quiet archival engraving or celestial-chart texture in the dark masthead, used at low opacity. It must contain no readable text, recognizable occult emblem, or hidden lore. Do not use a large crest, heavy ornamental frame, grungy noise, or decorative symbols that compete with state values.
- Section hierarchy: use spacing, typography, horizontal hairlines, and restrained semantic color. Never use a left-edge vertical bar, vertical rule, or repeated upright marker to distinguish sections, events, states, or inventory items.
- Layout: design for a 360–430 CSS-pixel chat column first. Prefer a portrait card near `9:16` or `3:5`; render at 2× density for delivery. Use one reading column, short labels, generous line height, and no horizontal table.
- Hierarchy: name and public identity → main/current fate thread → spirituality/sanity/pollution → states and pathway → money/inventory/companions. A player should understand the card in one downward scan.
- Tone: a clean Victorian occult case file from the world of *Lord of Mysteries*: pale paper, ink, fog-wine accents, restrained gold, gaslight-era typography. Avoid generic fantasy HUDs, neon magic, game-console chrome, parchment grunge, blood splatter, excessive gears, and dense steampunk ornament.

## Public semantic color

Color is supplemental public metadata, never a hidden appraisal system. Always keep the readable label; never rely on color alone.

- `ordinary` — ink `#403936`: mundane items and neutral information
- `clue` — dark old gold `#785416`: confirmed clues, formulas, or noteworthy evidence
- `extraordinary` — slate blue `#40556a`: publicly confirmed Beyonder materials, abilities, or spiritually unusual objects
- `warning` — ochre `#875814`: tension, light injury, significant danger, or temporary caution
- `danger` — wine red `#8a2438`: serious injury, severe contamination, or lethal risk
- `high_order` — muted violet `#58395f`: publicly confirmed high-order or occult influence
- `beneficial` — dark green `#355747`: healthy or explicitly beneficial public effects
- `critical` — oxblood `#4b1724`: near death, madness, disaster, or equivalent critical states

The ruleset has no universal rarity ladder for ordinary inventory. Do not infer rarity from an item name, price, narrative importance, or visual appearance. Inventory may carry `tone` and an optional `rank_label` only when the character has publicly established evidence. A sealed artifact grade, formula sequence, or material rank is displayed only if the authoritative state already contains it.

Existing rule-backed levels map as follows:

- event danger: 轻微 → ordinary, 显著 → clue, 严重 → warning, 致命 → danger, 灾难 → critical
- body and mind states use their explicit severity labels; healthy/clear states remain distinct from warning and dangerous states
- sequence color derives only from the public sequence number; it does not expose pathway secrets or hidden combat strength

Use the same mapping in HTML, SVG, rich text accents, captions, and generated-media metadata. Platforms without color keep the labels and optional `rank_label` unchanged.

## Illustration consent

After the first opening scene, panel, and choices, ask whether immersive illustrations should be enabled. If enabled, ask again only after qualifying key scenes and only after all core game information has been delivered.

The player can continue acting while an illustration is generated. Media completion does not reserve the turn or freeze the campaign.

## Key-scene qualification

Offer an illustration for:

- finalized player appearance
- first entrance into a major location
- first encounter with a key NPC or important item
- sequence advancement
- major relationship change
- fate-anchor deviation
- chapter climax or ending

Do not offer one for routine travel, shopping, repeated combat exchanges, rules questions, status checks, or media retries.

## Prompt grounding

Build prompts only from publicly established facts:

```text
Scene event: [event id and public scene title]
Time and place: [public time and location]
Subject: [public appearance, clothing, posture]
Environment: [details already described to the player]
Action: [current visible moment]
Mood: restrained Victorian occult mystery, fog, material detail, cinematic natural light
Continuity: [visual bible facts]
Exclude: readable UI text, hidden characters, secret symbols, future events, unconfirmed items, engine-only facts
Aspect ratio: [transport-appropriate]
```

Choose the best available image-generation capability at runtime. Provider-specific model names belong in deployment configuration, not campaign rules.

## Illustration art direction

Generated art should feel like a restrained illustrated novel plate rather than promotional game art:

- grounded Victorian clothing, architecture, gaslight, coal haze, wet stone, paper, brass, dark wood, and believable material detail
- low-saturation fog-wine, sepia, charcoal, cold gray, and dim amber; reserve supernatural color for the single established focal phenomenon
- readable silhouettes, one clear focal subject, quiet negative space, and cinematic natural or gaslight illumination
- character and item studies default to `4:5`; establishing scenes default to `3:4` or `4:5` for mobile chat; use wider ratios only when spatial geography is essential
- no readable generated text, fake UI, ornate borders, collages, character sheets with tiny labels, hidden observers, or decorative lore symbols that were not publicly established

State the visible moment and material facts before style language in the prompt. Keep mystery through partial visibility, atmosphere, and composition; do not turn ambiguity into visual spoilers.

## Visual bible

Store only public continuity facts:

```yaml
visuals:
  illustration_mode: ask
  character_bible:
    player:
      apparent_age: null
      build: null
      hair: null
      eyes: null
      clothing: []
      distinguishing_marks: []
  item_bible: {}
  last_scene_event_id: null
  transport_cache: {}
```

An image cannot establish new facts. If generated art introduces an unmentioned ring, scar, person, rune, or object, treat it as decorative noise unless later confirmed in text through a legitimate event.

## Safety and knowledge boundary

- Never place undiscovered villains, secret observers, hidden symbols, future injuries, pathway clues, or engine truth into an image.
- Never reveal a hidden object's appearance before the player sees it.
- Do not put private transport identifiers, filesystem paths, prompts containing hidden state, or credentials into metadata or captions.
- If an illustration conflicts with committed text, the text and state remain authoritative.
- Record media generation as a media event linked to the scene event; do not add it to the adventure journal unless it confirms no new facts.
