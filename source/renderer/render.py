#!/usr/bin/env python3
"""Export an honestly dated, static lock-screen PNG from a JSON configuration."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LEGACY_MILESTONES = ["Scope", "Reproduce", "Evaluate", "Explain", "Publish"]
NAVY = "#0A1424"
IVORY = "#F2EDDD"
AMBER = "#D9AF70"
MUTED = "#A9B3C0"


class ConfigError(ValueError):
    pass


def instant(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} is required as an ISO 8601 instant with UTC offset")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{field} must be an ISO 8601 instant") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ConfigError(f"{field} must include a UTC offset; an ambiguous local time is not accepted")
    return dt


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} is required")
    return value.strip()


def evidence_path(value, base, field):
    path = base / nonempty(value, field)
    if not path.is_file():
        raise ConfigError(f"{field} does not exist: {path}")
    return path


def validate_config(raw, base, preview=False):
    """Validate without changing the supplied progress ledger."""
    c = copy.deepcopy(raw)
    if not isinstance(c, dict):
        raise ConfigError("Configuration must be a JSON object")
    for field in ("goal", "title", "subtitle", "timezone", "default_action", "default_fallback"):
        c[field] = nonempty(c.get(field), field)
    try:
        ZoneInfo(c["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown IANA timezone: {c['timezone']}") from exc
    instant(c.get("deadline"), "deadline")
    for dim in ("width", "height"):
        if type(c.get(dim)) is not int or not 320 <= c[dim] <= 8000:
            raise ConfigError(f"{dim} must be an integer from 320 to 8000")
    ratio = c["height"] / c["width"]
    layout = c.get("layout", "landscape" if ratio < 1 else "portrait")
    if layout not in ("portrait", "landscape"):
        raise ConfigError("layout must be portrait or landscape")
    if layout == "portrait" and not 1.5 <= ratio <= 2.6:
        raise ConfigError("Portrait layout supports height/width from 1.5 to 2.6")
    if layout == "landscape" and not .45 <= ratio <= .85:
        raise ConfigError("Landscape layout supports height/width from 0.45 to 0.85")
    c["layout"] = layout
    if type(c.get("device_validated")) is not bool:
        raise ConfigError("device_validated must explicitly be true or false")
    if type(c.get("sample", False)) is not bool:
        raise ConfigError("sample must be true or false when present")
    if c.get("sample", False) and not preview:
        raise ConfigError("Sample configurations require --preview; they cannot produce a final export")
    milestone_order = c.get("milestone_order", LEGACY_MILESTONES)
    if (not isinstance(milestone_order, list) or len(milestone_order) != 5
            or not all(isinstance(name, str) and name.strip() for name in milestone_order)
            or len(set(milestone_order)) != 5):
        raise ConfigError("milestone_order must contain five distinct nonempty stage names")
    c["milestone_order"] = milestone_order
    milestones = c.get("milestones")
    if (not isinstance(milestones, list) or len(milestones) != len(milestone_order)
            or not all(isinstance(m, dict) for m in milestones)
            or [m.get("name") for m in milestones] != milestone_order):
        raise ConfigError(f"milestones must match milestone_order: {', '.join(milestone_order)}")
    for m in milestones:
        if type(m.get("completed")) is not bool:
            raise ConfigError(f"{m['name']}.completed must explicitly be true or false")
        if m["completed"]:
            evidence_path(m.get("evidence"), base, f"{m['name']}.evidence")
    completion = c.get("completion")
    if not isinstance(completion, dict) or type(completion.get("recorded")) is not bool:
        raise ConfigError("completion.recorded must explicitly be true or false")
    if completion["recorded"]:
        evidence_path(completion.get("evidence"), base, "completion.evidence")
    for field in ("display_name", "completion_headline", "completion_action", "completion_fallback",
                  "deadline_passed_action", "deadline_passed_fallback", "cover_message", "cover_credit"):
        if field in c:
            c[field] = nonempty(c[field], field)
    tasks = c.get("tasks")
    if not isinstance(tasks, list):
        raise ConfigError("tasks must be a dated list (an empty list uses the explicit default action)")
    capacity = c.get("daily_capacity_minutes")
    if capacity is not None and (type(capacity) is not int or capacity <= 0):
        raise ConfigError("daily_capacity_minutes must be a positive integer when supplied")
    dates, task_ids = set(), set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ConfigError(f"tasks[{i}] must be an object")
        try:
            day = datetime.strptime(task.get("date", ""), "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ConfigError(f"tasks[{i}].date must use YYYY-MM-DD") from exc
        if day != task["date"] or day in dates:
            raise ConfigError("Task dates must be unambiguous and unique")
        dates.add(day)
        for field in ("action", "fallback"):
            nonempty(task.get(field), f"tasks[{i}].{field}")
        for field in ("minutes", "fallback_minutes"):
            if type(task.get(field)) is not int or task[field] <= 0:
                raise ConfigError(f"tasks[{i}].{field} must be a positive integer")
        if task["fallback_minutes"] > task["minutes"]:
            raise ConfigError("Fallback effort cannot exceed normal effort")
        if capacity is not None and task["minutes"] > capacity:
            raise ConfigError(f"tasks[{i}] exceeds the recorded daily capacity")
        task["id"] = nonempty(task.get("id", day), f"tasks[{i}].id")
        if task["id"] in task_ids:
            raise ConfigError("Task IDs must be unique")
        task_ids.add(task["id"])
        task.setdefault("completed", False)
        if type(task["completed"]) is not bool:
            raise ConfigError(f"tasks[{i}].completed must be true or false")
        if task["completed"]:
            evidence_path(task.get("evidence"), base, f"tasks[{i}].evidence")
        task.setdefault("depends_on", [])
        task.setdefault("requires_milestones", [])
        if (not isinstance(task["depends_on"], list)
                or not all(isinstance(d, str) and d for d in task["depends_on"])):
            raise ConfigError(f"tasks[{i}].depends_on must be a list of task IDs")
        if (not isinstance(task["requires_milestones"], list)
                or not all(m in milestone_order for m in task["requires_milestones"])):
            raise ConfigError(f"tasks[{i}].requires_milestones must contain known milestone names")
    by_id = {t["id"]: t for t in tasks}
    visiting, visited = set(), set()

    def check_dependencies(task_id):
        if task_id in visiting:
            raise ConfigError("Task dependencies contain a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        task = by_id[task_id]
        for dependency in task["depends_on"]:
            if dependency not in by_id:
                raise ConfigError(f"Unknown task dependency: {dependency}")
            if by_id[dependency]["date"] > task["date"]:
                raise ConfigError("A task cannot depend on a later scheduled date")
            check_dependencies(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        check_dependencies(task_id)
    c["_artwork_path"] = str(evidence_path(c.get("artwork"), base, "artwork"))
    provenance = c.get("artwork_provenance", {})
    if not isinstance(provenance, dict):
        raise ConfigError("artwork_provenance must be an object")
    if not preview:
        if provenance.get("provider") != "Google Gemini":
            raise ConfigError("Final export requires actual artwork_provenance.provider = Google Gemini")
        evidence_path(provenance.get("evidence"), base, "artwork_provenance.evidence")
    fonts = c.get("fonts", {})
    if not isinstance(fonts, dict):
        raise ConfigError("fonts must be an object")
    for name, value in fonts.items():
        if name not in ("regular", "bold"):
            raise ConfigError(f"Unknown font option: {name}")
        evidence_path(value, base, f"fonts.{name}")
    c["_base"] = str(base)
    return c


def select_task(c, local_date):
    """Carry forward the earliest unfinished due work, respecting recorded prerequisites."""
    unfinished = sorted((t for t in c["tasks"] if t["date"] <= local_date and not t.get("completed", False)),
                        key=lambda t: (t["date"], t.get("id", t["date"])))
    if not unfinished:
        return None, None
    task = unfinished[0]
    by_id = {t.get("id", t["date"]): t for t in c["tasks"]}
    for dependency in task.get("depends_on", []):
        if not by_id[dependency].get("completed", False):
            return None, {"kind": "task", "name": by_id[dependency]["action"], "date": task["date"]}
    completed_stages = {m["name"] for m in c["milestones"] if m["completed"]}
    for stage in task.get("requires_milestones", []):
        if stage not in completed_stages:
            return None, {"kind": "milestone", "name": stage, "date": task["date"]}
    return task, None


def state_at(c, as_of):
    """Calendar dates control countdown; time never changes completion."""
    tz = ZoneInfo(c["timezone"])
    local = as_of.astimezone(tz)
    deadline = instant(c["deadline"], "deadline").astimezone(tz)
    days = (deadline.date() - local.date()).days
    recorded = c["completion"]["recorded"]
    if recorded:
        legacy_headline = "Published" if c["milestone_order"] == LEGACY_MILESTONES else "Completed"
        headline, caption = c.get("completion_headline", legacy_headline), "COMPLETION RECORDED"
    elif as_of >= deadline:
        headline, caption = "Deadline passed", "REVIEW THE PLAN"
    elif days == 0:
        headline, caption = "Due today", "BEFORE THE CUTOFF"
    else:
        headline, caption = str(days), "DAY TO LAUNCH" if days == 1 else "DAYS TO LAUNCH"
    task, blocked = select_task(c, local.date().isoformat())
    if recorded:
        action = c.get("completion_action", "Review the completed project and save its evidence")
        fallback = c.get("completion_fallback", "Save one lesson learned")
    elif as_of >= deadline:
        action = c.get("deadline_passed_action", "Review evidence and choose a new deadline")
        fallback = c.get("deadline_passed_fallback", "Record the next unfinished step")
    elif blocked and blocked["kind"] == "milestone":
        action = f"Review {blocked['name']} evidence before continuing"
        fallback = f"Write the missing {blocked['name']} requirement"
    elif blocked:
        action, fallback = "Finish the prerequisite: " + blocked["name"], "Record the missing prerequisite"
    else:
        action = task["action"] if task else c["default_action"]
        fallback = task["fallback"] if task else c["default_fallback"]
    using_task = task is not None and not recorded and as_of < deadline
    return {"as_of": local.isoformat(timespec="seconds"), "deadline": deadline.isoformat(),
            "calendar_days": days, "headline": headline, "caption": caption,
            "action": action, "fallback": fallback,
            "minutes": task["minutes"] if task and not recorded and as_of < deadline else None,
            "fallback_minutes": task["fallback_minutes"] if task and not recorded and as_of < deadline else None,
            "completed_milestones": sum(m["completed"] for m in c["milestones"]),
            "milestones": copy.deepcopy(c["milestones"]), "completion_recorded": recorded,
            "task_for_date": using_task and task["date"] == local.date().isoformat(),
            "selected_task_date": task["date"] if using_task else None,
            "carried_forward": using_task and task["date"] < local.date().isoformat(),
            "blocked_by": blocked if not recorded and as_of < deadline else None,
            "progress_basis": "Current recorded ledger; as-of changes countdown and task eligibility, not historical completion"}


def font(c, size, bold=False):
    from PIL import ImageFont
    key = "bold" if bold else "regular"
    custom = (c.get("fonts") or {}).get(key)
    path = Path(c["_base"]) / custom if custom else Path(__file__).parent / "fonts" / "Lexend.ttf"
    f = ImageFont.truetype(str(path), max(1, round(size)))
    if not custom:
        f.set_variation_by_axes([650 if bold else 400])
    return f


def wrapped(draw, text, f, max_width):
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=f) <= max_width:
            line = candidate
        else:
            if not line:
                raise ConfigError(f"Text contains a word wider than its layout area: {word}")
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def text_block(draw, c, text, x, y, width, size, max_lines, fill=IVORY, bold=False, align="left", min_size=None):
    current = round(size)
    minimum = round(min_size if min_size is not None else size * 0.8)
    while current >= minimum:
        f = font(c, current, bold)
        lines = wrapped(draw, text, f, width)
        if len(lines) <= max_lines:
            leading = round(current * 1.24)
            for i, line in enumerate(lines):
                dx = x + (width - draw.textlength(line, font=f)) / 2 if align == "center" else x
                draw.text((round(dx), round(y + i * leading)), line, font=f, fill=fill, anchor="lt")
            return len(lines) * leading
        current -= 1
    raise ConfigError(f"Text is too long for a legible export: {text!r}; shorten it in the configuration")


def render_wallpaper(c, state, preview=False):
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    w, h = c["width"], c["height"]
    scale = w / 1080
    canvas = Image.new("RGB", (w, h), NAVY)
    try:
        art = Image.open(c["_artwork_path"])
        art = ImageOps.exif_transpose(art).convert("RGB")
    except Exception as exc:
        raise ConfigError(f"Cannot decode artwork: {exc}") from exc
    contained = ImageOps.contain(art, (w, h), Image.Resampling.LANCZOS)
    art_x, art_y = (w - contained.width) // 2, (h - contained.height) // 2
    if c.get("layout") == "landscape":
        # The complete source remains contained. Soft padding and a narrow quiet-edge fade
        # avoid stretched pixel streaks; the workshop objects and watermark remain opaque.
        canvas = ImageOps.fit(art, (w, h), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(max(w, h) * .025))
        mask = Image.new("L", contained.size, 255)
        feather = min(round(min(w, h) * .025), contained.width // 20, contained.height // 20)
        md = ImageDraw.Draw(mask)
        if art_y:
            for i in range(feather):
                opacity = round(255 * i / max(1, feather-1))
                md.line([(0, i), (contained.width, i)], fill=opacity)
                md.line([(0, contained.height-1-i), (contained.width, contained.height-1-i)], fill=opacity)
        if art_x:
            for i in range(feather):
                opacity = round(255 * i / max(1, feather-1))
                md.line([(i, 0), (i, contained.height)], fill=opacity)
                md.line([(contained.width-1-i, 0), (contained.width-1-i, contained.height)], fill=opacity)
        canvas.paste(contained, (art_x, art_y), mask)
    else:
        canvas.paste(contained, (art_x, art_y))
    if c.get("layout") == "landscape":
        return render_landscape(canvas, c, state, preview)
    # Preserve the full artwork, adding a dark text field only over the information area.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(h):
        p = y / h
        if p < .26:
            alpha = 65
        elif p < .30:
            alpha = int(65 + (p - .26) / .04 * 170)
        elif p < .57:
            alpha = 235
        elif p < .64:
            alpha = int(235 * (1 - (p - .57) / .07))
        elif p >= .79:
            alpha = min(240, int(200 + (p - .79) / .11 * 40))
        else:
            alpha = 0
        od.line([(0, y), (w, y)], fill=(10, 20, 36, alpha))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(canvas)
    margin = round(w * .085)
    content_w = w - margin * 2
    # 0–27% is reserved for the real device status, date, clock, and widgets.
    if preview:
        label = "DESIGN PREVIEW · EXAMPLE DEADLINE" if c.get("sample") else "DATED PREVIEW · CURRENT RECORDS"
        text_block(d, c, label, margin, .275 * h, content_w, 27 * scale, 1, AMBER, True)
    head = state["headline"]
    if head.isdecimal():
        # Fit the vertical interval as well as the width on shorter portrait displays.
        headline_size = min(188 * scale, .078 * h)
        text_block(d, c, head, margin - 5 * scale, .303 * h, content_w, headline_size, 1, IVORY, True)
        caption_y = .386 * h
    else:
        headline_size = min(92 * scale, .045 * h)
        text_block(d, c, head, margin, .313 * h, content_w, headline_size, 1, IVORY, True,
                   min_size=min(55 * scale, headline_size))
        caption_y = .368 * h
    text_block(d, c, state["caption"], margin, caption_y, content_w, 27 * scale, 1, AMBER, True)
    text_block(d, c, c["title"], margin, .411 * h, content_w, 49 * scale, 1, IVORY, True)
    text_block(d, c, c["subtitle"], margin, .438 * h, content_w, 32 * scale, 1, MUTED)
    d.line([(margin, round(.466 * h)), (w - margin, round(.466 * h))], fill="#49505A", width=max(1, round(scale)))
    effort = f" · {state['minutes']} MIN" if state["minutes"] else ""
    text_block(d, c, "NEXT ACTION" + effort, margin, .478 * h, content_w, 24 * scale, 1, AMBER, True)
    used = text_block(d, c, state["action"], margin, .499 * h, content_w, 43 * scale, 2, IVORY, True, min_size=36 * scale)
    fallback_y = max(.550 * h, .499 * h + used + 18 * scale)
    fallback_effort = f"{state['fallback_minutes']} min: " if state["fallback_minutes"] else ""
    text_block(d, c, "Busy day · " + fallback_effort + state["fallback"], margin, fallback_y, content_w, 27 * scale, 2, MUTED, min_size=24 * scale)
    count = state["completed_milestones"]
    text_block(d, c, f"{count}/5 MILESTONES RECORDED", margin, .808 * h, content_w, 24 * scale, 1, MUTED, True)
    gap = content_w / 4
    for i, milestone in enumerate(c["milestones"]):
        cx = margin + i * gap
        cy = .839 * h
        r = round(5 * scale)
        if i < 4:
            d.line([(round(cx), round(cy)), (round(cx + gap), round(cy))], fill="#475461", width=max(1, round(2 * scale)))
        if milestone["completed"]:
            d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=AMBER)
        else:
            d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=NAVY, outline=MUTED, width=max(1, round(scale)))
        f = font(c, 23 * scale)
        label = milestone["name"]
        label_x = cx - d.textlength(label, font=f) / 2
        label_x = max(margin, min(label_x, w - margin - d.textlength(label, font=f)))
        d.text((round(label_x), round(.852 * h)), label, font=f, fill=MUTED, anchor="lt")
    deadline = instant(state["deadline"], "deadline")
    date_text = f"TARGET  {deadline.day} {deadline.strftime('%b %Y')} · {deadline.strftime('%H:%M')}"
    text_block(d, c, date_text, margin, .883 * h, content_w, 26 * scale, 1, IVORY)
    asof = instant(state["as_of"], "as_of")
    stamp = f"COUNTDOWN AS OF {asof.strftime('%d %b %Y · %H:%M')} · {c['timezone']}"
    text_block(d, c, stamp, margin, .902 * h, content_w, 22 * scale, 1, MUTED)
    return canvas


def render_landscape(canvas, c, state, preview=False):
    """Mac/display composition with top-center clock and bottom-center controls kept clear."""
    from PIL import Image, ImageChops, ImageDraw
    w, h = canvas.size
    scale = min(w / 2560, h / 1664)
    # Multiply two smooth gradients so no horizontal rectangle edge appears above the text.
    horizontal = Image.new("L", (w, 1))
    horizontal.putdata([218 if x / w < .43 else max(0, round(218 * (1 - (x / w - .43) / .15))) for x in range(w)])
    vertical = Image.new("L", (1, h))
    opacity = []
    for y in range(h):
        t = max(0, min(1, (y / h - .12) / .22))
        smooth = t * t * (3 - 2 * t)
        opacity.append(round(255 * (.25 + .75 * smooth)))
    vertical.putdata(opacity)
    alpha = ImageChops.multiply(horizontal.resize((w, h)), vertical.resize((w, h)))
    overlay = Image.new("RGBA", (w, h), (10, 20, 36, 0))
    overlay.putalpha(alpha)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(canvas)
    x, width = .08 * w, .36 * w
    if preview:
        label = "DESIGN PREVIEW · EXAMPLE DEADLINE" if c.get("sample") else "DATED PREVIEW · CURRENT RECORDS"
        text_block(d, c, label, x, .285 * h, width, 25 * scale, 1, AMBER, True)
    headline = state["headline"]
    deadline = instant(state["deadline"], "deadline").astimezone(ZoneInfo(c["timezone"]))
    target_date = deadline.strftime("%d %b %Y").upper()
    target_time = deadline.strftime("%H:%M %Z")
    if headline.isdecimal():
        size = min(226 * scale, .143 * h)
        text_block(d, c, headline, x - 5 * scale, .327 * h, width * .39, size, 1, IVORY, True, min_size=80 * scale)
        text_block(d, c, target_date, x + width * .48, .354 * h, width * .52, 43 * scale, 1, IVORY, True)
        text_block(d, c, target_time, x + width * .48, .402 * h, width * .52, 32 * scale, 1, AMBER, True)
        caption_y = .473 * h
    else:
        text_block(d, c, headline, x, .349 * h, width, 92 * scale, 1, IVORY, True, min_size=58 * scale)
        caption_y = .427 * h
        text_block(d, c, target_date, x, .470 * h, width * .52, 34 * scale, 1, IVORY, True)
        text_block(d, c, target_time, x + width * .56, .470 * h, width * .44, 31 * scale, 1, AMBER, True)
    text_block(d, c, state["caption"], x, caption_y, width, 26 * scale, 1, AMBER, True)
    text_block(d, c, c["title"], x, .518 * h, width, 55 * scale, 1, IVORY, True)
    text_block(d, c, c["subtitle"], x, .560 * h, width, 31 * scale, 1, MUTED)
    d.line([(round(x), round(.596 * h)), (round(x + width), round(.596 * h))], fill="#49505A", width=max(1, round(scale)))
    effort = f" · {state['minutes']} MIN" if state["minutes"] else ""
    tag = "NEXT ACTION" + (" · CARRY FORWARD" if state.get("carried_forward") else "") + effort
    text_block(d, c, tag, x, .616 * h, width, 23 * scale, 1, AMBER, True)
    used = text_block(d, c, state["action"], x, .646 * h, width, 40 * scale, 2, IVORY, True, min_size=34 * scale)
    fallback_y = max(.715 * h, .646 * h + used + 14 * scale)
    fallback_effort = f"{state['fallback_minutes']} min: " if state["fallback_minutes"] else ""
    text_block(d, c, "Busy day · " + fallback_effort + state["fallback"], x, fallback_y, width, 26 * scale, 2, MUTED, min_size=23 * scale)
    text_block(d, c, f"{state['completed_milestones']}/5 MILESTONES RECORDED", x, .802 * h, width, 22 * scale, 1, MUTED, True)
    # Keep even the final progress dot left of the bottom-center account controls.
    progress_width = min(width, .33 * w)
    gap = progress_width / 4
    for i, milestone in enumerate(c["milestones"]):
        cx, cy = x + i * gap, .838 * h
        r = max(2, round(4 * scale))
        if i < 4:
            d.line([(round(cx), round(cy)), (round(cx + gap), round(cy))], fill="#475461", width=max(1, round(2 * scale)))
        d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=AMBER if milestone["completed"] else NAVY,
                  outline=AMBER if milestone["completed"] else MUTED, width=max(1, round(scale)))
        f = font(c, 21 * scale)
        label = milestone["name"]
        label_width = d.textlength(label, font=f)
        lx = max(x, min(cx - label_width / 2, x + progress_width - label_width))
        d.text((round(lx), round(.851 * h)), label, font=f, fill=MUTED, anchor="lt")
    asof = instant(state["as_of"], "as_of")
    stamp = f"COUNTDOWN AS OF {asof.strftime('%d %b %Y · %H:%M')} · {c['timezone']}"
    text_block(d, c, stamp, x, .931 * h, width, 20 * scale, 1, MUTED)
    return canvas


def device_mockup(wallpaper, c):
    from PIL import Image, ImageDraw, ImageOps
    if c.get("layout") == "landscape":
        return landscape_mockup(wallpaper, c)
    # Generic presentation frame, deliberately not an installed-device screenshot.
    canvas = Image.new("RGB", (1200, 1500), "#EAE5D9")
    draw = ImageDraw.Draw(canvas)
    text_block(draw, c, c["title"], 70, 52, 1060, 37, 1, NAVY, True)
    text_block(draw, c, "GENERIC DEVICE MOCKUP · NOT AN INSTALLED SCREENSHOT", 70, 105, 1060, 20, 1, "#58606A")
    thumb = ImageOps.contain(wallpaper, (520, 1170), Image.Resampling.LANCZOS)
    x, y = (1200 - thumb.width) // 2, 200
    draw.rounded_rectangle((x-14, y-14, x+thumb.width+14, y+thumb.height+14), radius=54, fill="#222A34")
    mask = Image.new("L", thumb.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, thumb.width-1, thumb.height-1), radius=40, fill=255)
    canvas.paste(thumb, (x, y), mask)
    status = "Device layout verified" if c["device_validated"] else "Provisional fit · actual device view still required"
    text_block(draw, c, status, 70, 1420, 1060, 24, 1, NAVY, align="center")
    return canvas


def landscape_mockup(wallpaper, c):
    """Generic laptop frame with no simulated macOS interface."""
    from PIL import Image, ImageDraw, ImageOps
    canvas = Image.new("RGB", (1500, 1100), "#EAE5D9")
    d = ImageDraw.Draw(canvas)
    text_block(d, c, c["title"], 80, 60, 1340, 42, 1, NAVY, True)
    text_block(d, c, "GENERIC LAPTOP MOCKUP · NOT AN INSTALLED SCREENSHOT", 80, 120, 1340, 22, 1, "#58606A")
    thumb = ImageOps.contain(wallpaper, (1200, 700), Image.Resampling.LANCZOS)
    x, y = (1500 - thumb.width) // 2, 210
    d.rounded_rectangle((x-18, y-18, x+thumb.width+18, y+thumb.height+18), radius=28, fill="#232A32")
    canvas.paste(thumb, (x, y))
    base_y = y + thumb.height + 18
    d.polygon([(x-18, base_y), (x+thumb.width+18, base_y), (x+thumb.width+75, base_y+37), (x-75, base_y+37)], fill="#8A919A")
    d.rounded_rectangle((x-75, base_y+31, x+thumb.width+75, base_y+45), radius=8, fill="#737B85")
    status = f"{c['width']}×{c['height']} export · illustrative laptop preview"
    text_block(d, c, status, 80, 1040, 1340, 25, 1, NAVY, align="center")
    return canvas


def cover_image(wallpaper, c, state, preview=False):
    """A 3:2 presentation cover, labeled separately from the wallpaper itself."""
    from PIL import Image, ImageDraw, ImageOps
    if c.get("layout") == "landscape":
        return landscape_cover(wallpaper, c, state, preview)
    canvas = Image.new("RGB", (1500, 1000), "#EAE5D9")
    d = ImageDraw.Draw(canvas)
    text_block(d, c, "DESIGN PREVIEW" if preview else "STATIC WALLPAPER", 85, 85, 800, 24, 1, "#8F642D", True)
    text_block(d, c, c["title"], 85, 145, 800, 64, 1, NAVY, True)
    text_block(d, c, c["subtitle"], 85, 235, 800, 39, 2, NAVY)
    text_block(d, c, c.get("cover_message", "One clear goal. One useful next action."), 85, 355, 750, 45, 2, NAVY, True)
    text_block(d, c, "Gemini planning and artwork. ChatGPT coordination, review and dated export.", 85, 500, 720, 29, 3, "#58606A")
    d.line([(85, 650), (805, 650)], fill="#C8C2B7", width=2)
    deadline = instant(state["deadline"], "deadline")
    label = "EXAMPLE TARGET" if c.get("sample") else "PERSONAL TARGET"
    target = f"{label} · {deadline.strftime('%d %b %Y · %H:%M')}"
    text_block(d, c, target, 85, 685, 780, 23, 1, NAVY, True)
    asof = instant(state["as_of"], "as_of")
    text_block(d, c, f"As of {asof.strftime('%d %b %Y')} · {c['timezone']}", 85, 732, 780, 24, 1, "#58606A")
    countdown = f"{state['calendar_days']} calendar days" if state["headline"].isdecimal() else state["headline"]
    text_block(d, c, f"{countdown} · {state['completed_milestones']}/5 milestones recorded", 85, 778, 780, 25, 1, "#58606A")
    if not c["device_validated"]:
        text_block(d, c, "Provisional dimensions · check on your device", 85, 865, 790, 23, 1, "#8F642D", True)
    thumb = ImageOps.contain(wallpaper, (350, 780), Image.Resampling.LANCZOS)
    x, y = 1040 + (350 - thumb.width) // 2, 95
    d.rounded_rectangle((x-13, y-13, x+thumb.width+13, y+thumb.height+13), radius=45, fill="#222A34")
    mask = Image.new("L", thumb.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, thumb.width-1, thumb.height-1), radius=33, fill=255)
    canvas.paste(thumb, (x, y), mask)
    text_block(d, c, "GENERIC DEVICE MOCKUP", 970, 915, 470, 20, 1, NAVY, True, align="center")
    text_block(d, c, "Not an installed-device screenshot", 940, 948, 530, 18, 1, "#58606A", align="center")
    return canvas


def landscape_cover(wallpaper, c, state, preview=False):
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    # Present the original artwork generously, preserving every object and its watermark.
    art = ImageOps.exif_transpose(Image.open(c["_artwork_path"])).convert("RGB")
    canvas = ImageOps.fit(art, (1500, 1000), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(38))
    contained = ImageOps.contain(art, (1500, 1000), Image.Resampling.LANCZOS)
    art_x, art_y = (1500-contained.width)//2, (1000-contained.height)//2
    mask = Image.new("L", contained.size, 255)
    md = ImageDraw.Draw(mask)
    feather = min(35, contained.width//20, contained.height//20)
    if art_y:
        for i in range(feather):
            opacity = round(255 * i / max(1, feather-1))
            md.line([(0, i), (contained.width, i)], fill=opacity)
            md.line([(0, contained.height-1-i), (contained.width, contained.height-1-i)], fill=opacity)
    if art_x:
        for i in range(feather):
            opacity = round(255 * i / max(1, feather-1))
            md.line([(i, 0), (i, contained.height)], fill=opacity)
            md.line([(contained.width-1-i, 0), (contained.width-1-i, contained.height)], fill=opacity)
    canvas.paste(contained, (art_x, art_y), mask)
    d = ImageDraw.Draw(canvas)
    text_block(d, c, c["title"], 100, 125, 1300, 88, 1, IVORY, True)
    text_block(d, c, c["subtitle"], 105, 245, 1285, 45, 1, IVORY)
    deadline = instant(state["deadline"], "deadline").astimezone(ZoneInfo(c["timezone"]))
    label = deadline.strftime("%d %b %Y · %H:%M %Z").upper()
    if preview:
        label = ("EXAMPLE TARGET · " if c.get("sample") else "DATED PREVIEW · ") + label
    text_block(d, c, label, 105, 327, 1285, 28, 1, AMBER, True)
    return canvas


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--as-of", help="ISO 8601 instant with offset; default is the current instant")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--preview", action="store_true", help="Stamp an illustrative preview; never claim future progress")
    args = parser.parse_args(argv)
    try:
        path = args.config.resolve()
        c = validate_config(json.loads(path.read_text()), path.parent, args.preview)
        asof = instant(args.as_of, "as_of") if args.as_of else datetime.now().astimezone()
        state = state_at(c, asof)
        if asof > datetime.now().astimezone() and not args.preview:
            raise ConfigError("Future dates require --preview; do not present future views as real dated exports")
        wallpaper = render_wallpaper(c, state, args.preview)
        args.output.mkdir(parents=True, exist_ok=True)
        prefix = "preview" if args.preview else "wallpaper"
        date = state["as_of"][:10]
        primary = args.output / f"{prefix}-{date}.png"
        wallpaper.save(primary, "PNG", optimize=True)
        thumbnail = wallpaper.copy()
        thumbnail.thumbnail((1280, 832) if c["layout"] == "landscape" else (360, 800))
        thumbnail.save(args.output / f"{prefix}-{date}-small.png", "PNG")
        device_mockup(wallpaper, c).save(args.output / f"{prefix}-{date}-mockup.png", "PNG", optimize=True)
        cover_image(wallpaper, c, state, args.preview).save(args.output / f"{prefix}-{date}-cover.png", "PNG", optimize=True)
        manifest = {"kind": "illustrative preview" if args.preview else "static wallpaper export",
                    "device_validated": c["device_validated"], "width": c["width"], "height": c["height"],
                    "layout": c["layout"],
                    "goal": c["goal"], "project_title": c.get("display_name", c["title"] + " — " + c["subtitle"]), "state": state,
                    "artwork": c["artwork"], "artwork_provenance": c.get("artwork_provenance"),
                    "artwork_sha256": hashlib.sha256(Path(c["_artwork_path"]).read_bytes()).hexdigest(),
                    "png_sha256": hashlib.sha256(primary.read_bytes()).hexdigest(),
                    "note": "Static PNG; replace wallpaper manually after each fresh export. No reminders or device installation performed."}
        (args.output / f"{prefix}-{date}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Exported {primary.resolve()} ({c['width']}×{c['height']}); {state['headline']}; {state['completed_milestones']}/5 recorded")
        return 0
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"Export stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
