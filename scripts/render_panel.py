#!/usr/bin/env python3
"""Render a public campaign panel model as self-contained HTML or SVG."""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "name",
    "identity",
    "location",
    "main",
    "current",
    "spirituality",
    "sanity",
    "pollution",
    "money",
    "body_state",
    "mind_state",
    "sequence",
    "pathway",
    "acting",
    "inventory",
    "state_revision",
)

BODY_STATES = {"健康", "轻伤", "重伤", "濒死", "失控倾向", "灵性枯竭"}
MIND_STATES = {"清醒", "紧张", "焦虑", "恍惚", "疯狂"}
VISUAL_TONES = {"ordinary", "clue", "extraordinary", "warning", "danger", "high_order", "beneficial", "critical"}
TONE_COLORS = {
    "ordinary": "#403936",
    "clue": "#785416",
    "extraordinary": "#40556a",
    "warning": "#875814",
    "danger": "#8a2438",
    "high_order": "#58395f",
    "beneficial": "#355747",
    "critical": "#4b1724",
}
BODY_TONES = {"健康": "beneficial", "轻伤": "warning", "重伤": "danger", "濒死": "critical", "失控倾向": "high_order", "灵性枯竭": "extraordinary"}
MIND_TONES = {"清醒": "extraordinary", "紧张": "warning", "焦虑": "danger", "恍惚": "high_order", "疯狂": "critical"}
EVENT_TONES = {"轻微": "ordinary", "显著": "clue", "严重": "warning", "致命": "danger", "灾难": "critical"}
MASTHEAD_ART = Path(__file__).resolve().parent.parent / "assets" / "dossier-masthead-engraving.png"


def fail(message: str) -> None:
    raise ValueError(message)


def load_model(path: Path) -> dict[str, Any]:
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read panel JSON: {exc}")
    if not isinstance(model, dict):
        fail("panel JSON must be an object")
    return model


def validate(model: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in model]
    if missing:
        fail("missing required fields: " + ", ".join(missing))

    for field in ("name", "identity", "location", "main", "current", "money", "sequence", "pathway", "acting"):
        if not isinstance(model[field], str) or not model[field].strip():
            fail(f"{field} must be a non-empty string")

    spirituality = model["spirituality"]
    if not isinstance(spirituality, dict):
        fail("spirituality must be an object")
    current = spirituality.get("current")
    maximum = spirituality.get("max")
    if not isinstance(current, int) or not isinstance(maximum, int) or maximum < 1 or current < 0 or current > maximum:
        fail("spirituality must satisfy 0 <= current <= max and max >= 1")

    for field in ("sanity", "pollution"):
        value = model[field]
        if not isinstance(value, int) or not 0 <= value <= 100:
            fail(f"{field} must be an integer from 0 to 100")

    if model["body_state"] not in BODY_STATES:
        fail("invalid body_state")
    if model["mind_state"] not in MIND_STATES:
        fail("invalid mind_state")

    effects = model.get("effects", [])
    if not isinstance(effects, list) or len(effects) > 4:
        fail("effects must be an array with at most 4 items")
    validate_entries(effects, "effects")

    if not isinstance(model["inventory"], list) or len(model["inventory"]) > 6:
        fail("inventory must be an array with at most 6 items")
    validate_entries(model["inventory"], "inventory")

    current_event = model.get("current_event")
    if current_event is not None:
        if not isinstance(current_event, dict) or not isinstance(current_event.get("label"), str) or not current_event["label"].strip():
            fail("current_event requires a non-empty label")
        if current_event.get("danger_level") not in EVENT_TONES:
            fail("invalid current_event danger_level")

    companions = model.get("companions", [])
    if not isinstance(companions, list):
        fail("companions must be an array")
    for companion in companions:
        if not isinstance(companion, dict) or not companion.get("name") or not companion.get("status"):
            fail("each companion requires name and status")

    revision = model["state_revision"]
    if not isinstance(revision, int) or revision < 1:
        fail("state_revision must be a positive integer")


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def validate_entries(items: list[Any], field: str) -> None:
    for item in items:
        if isinstance(item, str):
            if not item.strip():
                fail(f"{field} items must be non-empty")
            continue
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            fail(f"{field} entries require a non-empty name")
        if item.get("tone", "ordinary") not in VISUAL_TONES:
            fail(f"invalid {field} tone")
        rank = item.get("rank_label")
        if rank is not None and (not isinstance(rank, str) or not rank.strip()):
            fail(f"{field} rank_label must be null or a non-empty string")


def normalize_entries(items: list[Any], default_names: list[str] | None = None) -> list[dict[str, str | None]]:
    source = items or (default_names or [])
    result: list[dict[str, str | None]] = []
    for item in source:
        if isinstance(item, str):
            result.append({"name": item, "tone": "ordinary", "rank_label": None})
        else:
            result.append({"name": item["name"], "tone": item.get("tone", "ordinary"), "rank_label": item.get("rank_label")})
    return result


def tone_color(tone: str) -> str:
    return TONE_COLORS.get(tone, TONE_COLORS["ordinary"])


def masthead_art_data_uri() -> str:
    if not MASTHEAD_ART.is_file():
        return ""
    encoded = base64.b64encode(MASTHEAD_ART.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def sequence_tone(sequence: str) -> str:
    if sequence == "凡人":
        return "ordinary"
    digits = "".join(character for character in sequence if character.isdigit())
    if not digits:
        return "extraordinary"
    level = int(digits)
    if level >= 7:
        return "extraordinary"
    if level >= 5:
        return "clue"
    if level >= 3:
        return "danger"
    if level >= 1:
        return "high_order"
    return "critical"


def display_name(model: dict[str, Any]) -> str:
    nickname = model.get("nickname")
    return f"{model['name']}（{nickname}）" if nickname else model["name"]


def inventory_text(model: dict[str, Any]) -> str:
    items = normalize_entries(model["inventory"], ["数枚便士", "一份旧报纸"])
    return " · ".join(str(item["name"]) for item in items)


def companions_text(model: dict[str, Any]) -> str:
    return " · ".join(f"{item['name']}（{item['status']}）" for item in model.get("companions", []))


def wrap_inventory(model: dict[str, Any], width: int, max_lines: int) -> list[str]:
    items = [str(item["name"]) for item in normalize_entries(model["inventory"], ["数枚便士", "一份旧报纸"])]
    lines: list[str] = []
    current = ""
    for item in items:
        candidate = item if not current else f"{current} · {item}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = item
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def wrap_chars(value: str, width: int, max_lines: int) -> list[str]:
    text = str(value).strip()
    if not text:
        return [""]
    if len(text) <= width * max_lines:
        line_count = min(max_lines, (len(text) + width - 1) // width)
        step = (len(text) + line_count - 1) // line_count
        return [text[index : index + step] for index in range(0, len(text), step)]
    lines = [text[index : index + width] for index in range(0, len(text), width)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def render_html(model: dict[str, Any]) -> str:
    spirit = model["spirituality"]
    percent = round(spirit["current"] / spirit["max"] * 100)
    companions = companions_text(model)
    effects = normalize_entries(model.get("effects", []))
    inventory = normalize_entries(model["inventory"], ["数枚便士", "一份旧报纸"])
    companion_block = f'<div class="row"><span>同行</span><strong>{e(companions)}</strong></div>' if companions else ""
    effect_chips = "".join(f'<span class="effect" style="color:{tone_color(str(item["tone"]))}">{e(item["name"])}</span>' for item in effects)
    inventory_grid = "".join(
        f'<div class="item" style="color:{tone_color(str(item["tone"]))}"><span>{e(item["name"])}</span>'
        + (f'<small>{e(item["rank_label"])}</small>' if item["rank_label"] else "")
        + "</div>"
        for item in inventory
    )
    current_event = model.get("current_event")
    event_badge = ""
    if current_event:
        event_tone = EVENT_TONES[current_event["danger_level"]]
        event_badge = f'<div class="event" style="color:{tone_color(event_tone)}"><b>{e(current_event["danger_level"])}</b><span>{e(current_event["label"])}</span></div>'
    body_color = tone_color(BODY_TONES[model["body_state"]])
    mind_color = tone_color(MIND_TONES[model["mind_state"]])
    sequence_color = tone_color(sequence_tone(model["sequence"]))
    world_time = model.get("world_time") or "时间未记录"
    masthead_art = masthead_art_data_uri()
    masthead_style = f"--masthead-art:url('{masthead_art}')" if masthead_art else ""
    accessible = (
        f"{display_name(model)}，位于{model['location']}，身体{model['body_state']}，"
        f"精神{model['mind_state']}，灵性{spirit['current']}比{spirit['max']}，"
        f"理智{model['sanity']}，污染{model['pollution']}。"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(display_name(model))} · 状态</title>
<style>
:root{{--wine:#6d1f2e;--oxblood:#3a0d16;--gold:#785416;--paper:#fbf8f2;--ink:#282321;--muted:#716a64;--line:#ddd2c4;}}
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:#ddd9d2;color:var(--ink)}}
body{{padding:12px;font-family:"Kaiti SC","STKaiti","Noto Serif CJK SC",serif}}
.card{{width:min(420px,100%);margin:auto;padding:0 24px 24px;border-radius:10px;background:var(--paper);box-shadow:0 12px 34px rgba(58,13,22,.12);overflow:hidden}}
.topline{{display:flex;justify-content:space-between;margin:0 -24px;padding:18px 24px 10px;background:var(--oxblood);font:700 10px "PingFang SC",sans-serif;letter-spacing:1.5px;color:#d6b86f}}
.topline,.hero{{position:relative;isolation:isolate}}
.topline:before,.hero:before{{content:"";position:absolute;z-index:-1;inset:0;background-image:linear-gradient(rgba(58,13,22,.63),rgba(58,13,22,.84)),var(--masthead-art);background-size:cover;background-position:center top;opacity:.46}}
.hero{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;margin:0 -24px;padding:8px 24px 24px;background:var(--oxblood);color:#fffaf3}}
.eyebrow,.label{{font:700 11px "PingFang SC",sans-serif;letter-spacing:2px;color:var(--wine)}}
h1{{margin:7px 0 9px;font-family:"Songti SC","STSong","Noto Serif CJK SC",serif;font-size:34px;line-height:1.12;overflow-wrap:anywhere}}
.identity,.location{{margin:5px 0;font-size:14px;line-height:1.55;color:#d8ccc2}}
.seal{{display:none}}
.event{{align-self:end;min-width:76px;padding:7px 9px;background:rgba(251,248,242,.94);box-shadow:inset 0 -1px currentColor;text-align:left;font:700 10px "PingFang SC",sans-serif;letter-spacing:1px}}
.event b,.event span{{display:block}}.event b{{margin-bottom:4px;font-size:12px}}
.fate{{padding:22px 4px 8px;border-bottom:1px solid var(--line)}}
.thread{{margin:11px 0 17px}}
.thread span{{display:block;margin-bottom:5px;color:var(--muted);font:700 10px "PingFang SC",sans-serif;letter-spacing:1.5px}}
.thread.current span{{color:var(--wine)}}
.thread strong{{font-size:16px;font-weight:500;line-height:1.55;overflow-wrap:anywhere}}
.stats{{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:18px;padding:20px 2px 18px;border-bottom:1px solid var(--line)}}
.stat{{padding:0}}
.stat.spirit{{grid-column:auto}}
.stat label{{display:block;color:var(--muted);font:700 10px "PingFang SC",sans-serif;letter-spacing:1.5px}}
.value{{display:flex;align-items:baseline;gap:5px;margin-top:5px;font:700 34px "Avenir Next Condensed","PingFang SC",sans-serif}}
.value small{{font-size:13px;color:var(--muted)}}
.bar{{height:5px;margin-top:8px;background:#d9d1c7;overflow:hidden}}
.bar i{{display:block;width:{percent}%;height:100%;background:var(--wine)}}
.details{{display:grid;gap:12px;padding:18px 2px 0}}
.row{{display:grid;grid-template-columns:58px minmax(0,1fr);gap:10px;align-items:start;font-size:14px;line-height:1.55}}
.row span{{color:var(--muted);font:700 10px "PingFang SC",sans-serif;letter-spacing:1.5px}}
.row strong{{font-weight:500;overflow-wrap:anywhere}}
.chips{{display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:4px;font:700 13px "PingFang SC",sans-serif}}
.state{{padding-bottom:3px;border-bottom:2px solid currentColor}}
.effect{{font-size:12px;font-weight:600}}
.inventory{{padding-top:4px;border-top:1px solid var(--line)}}
.inventory h2{{margin:12px 0 10px;font:700 10px "PingFang SC",sans-serif;letter-spacing:1.5px;color:var(--muted)}}
.inventory-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}
.item{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:baseline;padding-bottom:5px;border-bottom:1px solid rgba(113,106,100,.18);font-size:14px;line-height:1.4}}
.item small{{font:700 9px "PingFang SC",sans-serif;letter-spacing:1px}}
.sr{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
@media(max-width:360px){{body{{padding:6px}}.card{{padding:0 20px 21px}}.topline,.hero{{margin-left:-20px;margin-right:-20px;padding-left:20px;padding-right:20px}}h1{{font-size:30px}}.stats{{grid-template-columns:1.2fr 1fr 1fr}}.value{{font-size:30px}}}}
</style>
</head>
<body>
<main class="card" style="{masthead_style}" aria-label="{e(accessible)}">
  <p class="sr">{e(accessible)}</p>
  <div class="topline"><span>{e(world_time)}</span><span>STATE / {model['state_revision']:03d}</span></div>
  <section class="hero">
    <div><div class="eyebrow">状态</div><h1>{e(display_name(model))}</h1><p class="identity">{e(model['identity'])}</p><p class="location">{e(model['location'])}</p></div>
    {event_badge}
  </section>
  <section class="fate"><div class="label">命运线</div><div class="thread"><span>主线</span><strong>{e(model['main'])}</strong></div><div class="thread current"><span>当下</span><strong>{e(model['current'])}</strong></div></section>
  <section class="stats">
    <div class="stat spirit"><label>灵性</label><div class="value">{spirit['current']}<small>/ {spirit['max']}</small></div><div class="bar"><i></i></div></div>
    <div class="stat"><label>理智</label><div class="value">{model['sanity']}<small>/ 100</small></div></div>
    <div class="stat"><label>污染</label><div class="value">{model['pollution']}<small>/ 100</small></div></div>
  </section>
  <section class="details">
    <div class="chips"><span class="state" style="color:{body_color}">{e(model['body_state'])}</span><span class="state" style="color:{mind_color}">{e(model['mind_state'])}</span>{effect_chips}</div>
    <div class="row"><span>序列</span><strong style="color:{sequence_color}">{e(model['sequence'])}</strong></div>
    <div class="row"><span>途径</span><strong>{e(model['pathway'])}</strong></div>
    <div class="row"><span>扮演度</span><strong>{e(model['acting'])}</strong></div>
    <div class="row"><span>金钱</span><strong>{e(model['money'])}</strong></div>
    {companion_block}
  </section>
  <section class="inventory"><h2>随身物品</h2><div class="inventory-grid">{inventory_grid}</div></section>
</main>
</body>
</html>
"""


def svg_text_lines(lines: list[str], x: int, y: int, line_height: int, css_class: str) -> str:
    return "".join(
        f'<text x="{x}" y="{y + index * line_height}" class="{css_class}">{e(line)}</text>'
        for index, line in enumerate(lines)
    )


def svg_inventory_grid(entries: list[dict[str, str | None]]) -> str:
    blocks = []
    for index, item in enumerate(entries):
        column = index % 2
        row = index // 2
        x = 54 + column * 314
        y = 1182 + row * 48
        name = wrap_chars(str(item["name"]), 10, 1)[0]
        color = tone_color(str(item["tone"]))
        rank = f'<text x="{x + 278}" y="{y}" text-anchor="end" class="utility" fill="{color}" font-size="14" font-weight="700">{e(item["rank_label"])}</text>' if item["rank_label"] else ""
        blocks.append(f'<text x="{x}" y="{y}" class="body" fill="{color}" font-size="23">{e(name)}</text>{rank}<line x1="{x}" y1="{y + 12}" x2="{x + 278}" y2="{y + 12}" stroke="#e7ded3"/>')
    return "".join(blocks)


def svg_effect_grid(entries: list[dict[str, str | None]]) -> str:
    blocks = []
    for index, item in enumerate(entries):
        column = index % 2
        row = index // 2
        x = 152 + column * 256
        y = 938 + row * 34
        blocks.append(f'<text x="{x}" y="{y}" class="body" fill="{tone_color(str(item["tone"]))}" font-size="22">{e(wrap_chars(str(item["name"]), 9, 1)[0])}</text>')
    return "".join(blocks)


def render_svg(model: dict[str, Any]) -> str:
    spirit = model["spirituality"]
    percent = spirit["current"] / spirit["max"]
    bar_width = round(252 * percent)
    main_lines = wrap_chars(model["main"], 18, 2)
    current_lines = wrap_chars(model["current"], 18, 2)
    has_companions = bool(model.get("companions"))
    inventory = normalize_entries(model["inventory"], ["数枚便士", "一份旧报纸"])
    effects = normalize_entries(model.get("effects", []))
    name_lines = wrap_chars(display_name(model), 12, 1)
    name_font_size = 52 if len(display_name(model)) <= 9 else 42
    identity_lines = wrap_chars(model["identity"], 24, 1)
    location_lines = wrap_chars(model["location"], 24, 1)
    world_time = model.get("world_time") or "时间未记录"
    companion_lines = wrap_chars(companions_text(model), 20, 1) if has_companions else []
    companion_svg = ""
    if companion_lines:
        companion_svg = '<text x="54" y="1320" class="label muted">同行</text>' + svg_text_lines(companion_lines, 150, 1320, 34, "body ink")
    effects_svg = ('<text x="54" y="938" class="label muted">效果</text>' + svg_effect_grid(effects)) if effects else ""
    inventory_svg = svg_inventory_grid(inventory)
    body_color = tone_color(BODY_TONES[model["body_state"]])
    mind_color = tone_color(MIND_TONES[model["mind_state"]])
    body_underline_end = 142 + len(model["body_state"]) * 25
    mind_underline_end = 310 + len(model["mind_state"]) * 25
    sequence_color = tone_color(sequence_tone(model["sequence"]))
    sanity_color = tone_color("ordinary" if model["sanity"] >= 70 else "warning" if model["sanity"] >= 40 else "danger" if model["sanity"] >= 10 else "critical")
    pollution_color = tone_color("ordinary" if model["pollution"] <= 20 else "warning" if model["pollution"] <= 40 else "danger" if model["pollution"] <= 60 else "high_order")
    current_event = model.get("current_event")
    masthead_art = masthead_art_data_uri()
    masthead_image = f'<image x="18" y="18" width="684" height="300" preserveAspectRatio="xMidYMid slice" opacity="0.32" href="{masthead_art}"/>' if masthead_art else ""
    event_svg = ""
    if current_event:
        event_color = tone_color(EVENT_TONES[current_event["danger_level"]])
        event_svg = f'<rect x="514" y="96" width="152" height="74" fill="#fbf8f2" fill-opacity=".94"/><line x1="530" y1="160" x2="650" y2="160" stroke="{event_color}"/><text x="530" y="124" class="utility" fill="{event_color}" font-size="15" font-weight="700" letter-spacing="1">{e(current_event["danger_level"])}</text><text x="530" y="153" class="body" fill="#403936" font-size="20">{e(wrap_chars(current_event["label"], 7, 1)[0])}</text>'
    accessible = (
        f"{display_name(model)}，位于{model['location']}，身体{model['body_state']}，"
        f"精神{model['mind_state']}，灵性{spirit['current']}比{spirit['max']}，"
        f"理智{model['sanity']}，污染{model['pollution']}。"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1360" viewBox="0 0 720 1360" role="img" aria-labelledby="title desc">
<title id="title">{e(display_name(model))}状态面板</title><desc id="desc">{e(accessible)}</desc>
<defs><style>.display{{font-family:"Songti SC","STSong","Noto Serif CJK SC",serif}}.body{{font-family:"Kaiti SC","STKaiti","Noto Serif CJK SC",serif;font-size:26px}}.utility{{font-family:"Avenir Next Condensed","PingFang SC",sans-serif}}.ink{{fill:#282321}}.muted{{fill:#716a64}}.wineText{{fill:#6d1f2e}}.label{{font-family:"PingFang SC",sans-serif;font-size:18px;font-weight:700;letter-spacing:2px}}</style></defs>
<rect width="720" height="1360" fill="#d8d4ce"/><rect x="18" y="18" width="684" height="1324" rx="12" fill="#fbf8f2"/><rect x="18" y="18" width="684" height="300" rx="12" fill="#3a0d16"/><rect x="18" y="296" width="684" height="22" fill="#3a0d16"/>{masthead_image}
<text x="54" y="60" class="utility" fill="#d6b86f" font-size="15" font-weight="700" letter-spacing="2">{e(world_time)}</text><text x="666" y="60" text-anchor="end" class="utility" fill="#bcaeaa" font-size="15" font-weight="700" letter-spacing="2">DOSSIER / {model['state_revision']:03d}</text>
<text x="54" y="112" class="utility" fill="#d6b86f" font-size="17" font-weight="700" letter-spacing="4">公开状态</text><text x="54" y="180" class="display" fill="#fffaf3" font-size="{name_font_size}" font-weight="700">{e(name_lines[0])}</text><text x="54" y="232" class="body" fill="#d8ccc2">{e(identity_lines[0])}</text><text x="54" y="274" class="body" fill="#bcaeaa">{e(location_lines[0])}</text>{event_svg}
<text x="54" y="364" class="label wineText">命运线</text><text x="54" y="410" class="label muted">主线</text>{svg_text_lines(main_lines, 54, 448, 38, 'body ink')}<line x1="54" y1="532" x2="666" y2="532" stroke="#ddd2c4"/><text x="54" y="579" class="label wineText">当下</text>{svg_text_lines(current_lines, 54, 615, 38, 'body ink')}
<line x1="54" y1="686" x2="666" y2="686" stroke="#ddd2c4"/><text x="54" y="725" class="label muted">灵性</text><text x="54" y="795" class="utility wineText" font-size="68" font-weight="700">{spirit['current']}</text><text x="138" y="792" class="utility muted" font-size="23">/ {spirit['max']}</text><rect x="54" y="816" width="252" height="7" fill="#d9d1c7"/><rect x="54" y="816" width="{bar_width}" height="7" fill="#6d1f2e"/>
<text x="358" y="725" class="label muted">理智</text><text x="358" y="795" class="utility" fill="{sanity_color}" font-size="60" font-weight="700">{model['sanity']}</text><text x="450" y="792" class="utility muted" font-size="20">/100</text><text x="528" y="725" class="label muted">污染</text><text x="528" y="795" class="utility" fill="{pollution_color}" font-size="60" font-weight="700">{model['pollution']}</text><text x="592" y="792" class="utility muted" font-size="20">/100</text>
<line x1="54" y1="856" x2="666" y2="856" stroke="#ddd2c4"/><text x="54" y="898" class="label muted">状态</text><text x="142" y="898" class="body" fill="{body_color}" font-size="25" font-weight="700">{e(model['body_state'])}</text><line x1="142" y1="909" x2="{body_underline_end}" y2="909" stroke="{body_color}" stroke-width="3"/><text x="310" y="898" class="body" fill="{mind_color}" font-size="25" font-weight="700">{e(model['mind_state'])}</text><line x1="310" y1="909" x2="{mind_underline_end}" y2="909" stroke="{mind_color}" stroke-width="3"/>{effects_svg}
<line x1="54" y1="986" x2="666" y2="986" stroke="#ddd2c4"/><text x="54" y="1028" class="label muted">序列</text><text x="142" y="1028" class="body" fill="{sequence_color}">{e(model['sequence'])}</text><text x="354" y="1028" class="label muted">扮演度</text><text x="466" y="1028" class="body ink">{e(model['acting'])}</text><text x="54" y="1074" class="label muted">途径</text><text x="142" y="1074" class="body ink">{e(model['pathway'])}</text><text x="354" y="1074" class="label muted">金钱</text><text x="466" y="1074" class="body" fill="#785416">{e(model['money'])}</text>
<line x1="54" y1="1104" x2="666" y2="1104" stroke="#ddd2c4"/><text x="54" y="1140" class="label muted">随身物品</text>{inventory_svg}{companion_svg}
</svg>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="public panel JSON")
    parser.add_argument("--format", required=True, choices=("html", "svg"))
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        model = load_model(args.input)
        validate(model)
        rendered = render_html(model) if args.format == "html" else render_svg(model)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
