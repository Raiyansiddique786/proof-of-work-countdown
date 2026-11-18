#!/usr/bin/env python3
"""Build the one-page project summary from an executed wallpaper manifest.

Requires reportlab and Pillow. Uses the latest dated manifest in exports/current
unless --manifest is supplied. This command does not export a wallpaper or
change milestone status.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
NAVY = colors.HexColor("#0B1526")
IVORY = colors.HexColor("#F5F0E7")
AMBER = colors.HexColor("#DBAD65")
INK = colors.HexColor("#182539")
MUTED = colors.HexColor("#526173")
LINE = colors.HexColor("#D8D5CB")


def paragraph(c, text, x, top, width, size=9, color=INK, leading=None, font="Body"):
    """Place a paragraph by its top edge, and return its bottom edge."""
    style = ParagraphStyle("text", fontName=font, fontSize=size,
                           leading=leading or size * 1.38, textColor=color,
                           alignment=TA_LEFT, spaceBefore=0, spaceAfter=0)
    p = Paragraph(text, style)
    _, height = p.wrap(width, 800)
    p.drawOn(c, x, top - height)
    return top - height


def text(c, content, x, y, size=9, color=INK, font="Body"):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, str(content))


def label(c, content, x, y, color=MUTED, size=7.3):
    c.saveState()
    c.setFillColor(color)
    t = c.beginText(x, y)
    t.setFont("Body", size)
    t.setCharSpace(1.05)
    t.textOut(content)
    c.drawText(t)
    c.restoreState()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "final-entry/project-summary.pdf")
    args = parser.parse_args()
    manifests = sorted((ROOT / "exports/current").glob("wallpaper-????-??-??.json"))
    if args.manifest is None and not manifests:
        parser.error("Export a dated wallpaper first; no manifest exists.")
    manifest_path = (args.manifest or manifests[-1]).resolve()
    data = json.loads(manifest_path.read_text())
    config = json.loads((ROOT / "config/project.json").read_text())
    state = data["state"]
    zone = ZoneInfo(config["timezone"])
    as_of = datetime.fromisoformat(state["as_of"]).astimezone(zone)
    deadline = datetime.fromisoformat(state["deadline"]).astimezone(zone)
    date_label = as_of.strftime("%d %b %Y").lstrip("0")
    due_label = deadline.strftime("%d %B %Y").lstrip("0")
    due_time = deadline.strftime("%H:%M")
    zone_label = deadline.tzname() or config["timezone"]
    stages = config["milestones"]
    # Avoid publishing a new status beside an older wallpaper snapshot.
    configured_stages = [(m["name"], bool(m["completed"])) for m in stages]
    exported_stages = [(m["name"], bool(m["completed"])) for m in state["milestones"]]
    if configured_stages != exported_stages:
        parser.error("Milestone status changed after this export. Re-export the wallpaper before the PDF.")
    device_checked = bool(config.get("device_validated")) and bool(
        config.get("device", {}).get("lock_screen_fit_verified"))
    stage_status = {m["name"]: bool(m["completed"]) for m in stages}
    completed = sum(bool(m["completed"]) for m in stages)
    total = len(stages)
    png = manifest_path.with_suffix(".png")
    if not png.is_file():
        parser.error(f"Manifest's matching wallpaper is missing: {png}")
    scratch = ROOT / "tmp/pdfs"
    scratch.mkdir(parents=True, exist_ok=True)
    preview = scratch / "summary-wallpaper-preview.png"
    with Image.open(png) as im:
        im.thumbnail((1100, 800), Image.Resampling.LANCZOS)
        im.convert("RGB").save(preview)
    font = ROOT / "renderer/fonts/Lexend.ttf"
    pdfmetrics.registerFont(TTFont("Body", str(font)))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    c.setTitle(config.get("display_name", "PROOF OF WORK - My Countdown Project Launch"))
    c.setAuthor("PROOF OF WORK")
    c.setSubject("A static countdown wallpaper with evidence-based milestones and a manual refresh workflow")
    w, h = A4
    margin = 36
    usable = w - 2 * margin
    c.setFillColor(IVORY)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, h - 112, w, 112, fill=1, stroke=0)
    label(c, "ONE DEADLINE / FIVE STAGES / ONE NEXT ACTION", margin, h - 27, AMBER, 7.4)
    text(c, config["title"], margin, h - 64, 30, IVORY)
    text(c, config["subtitle"], margin, h - 88, 12.5, IVORY)

    # Wallpaper preview and two separate signals: time and recorded work.
    image_top = h - 134
    image_w = 326
    image_h = image_w * data["height"] / data["width"]
    c.drawImage(str(preview), margin, image_top - image_h,
                width=image_w, height=image_h, mask="auto")
    info_x = margin + image_w + 18
    info_w = w - margin - info_x
    headline = str(state["headline"])
    headline_size = 54 if headline.isdigit() else 18
    text(c, headline, info_x, image_top - 51, headline_size, INK)
    label(c, str(state["caption"]).upper(), info_x, image_top - 70, MUTED, 6.4)
    text(c, f"As of {date_label}", info_x, image_top - 90, 8.4, MUTED)
    c.setStrokeColor(LINE)
    c.line(info_x, image_top - 105, w - margin, image_top - 105)
    text(c, f"{completed}/{total}", info_x, image_top - 137, 24, INK)
    label(c, "STAGES RECORDED", info_x, image_top - 155, MUTED, 6.4)
    paragraph(c, "Time passing never completes a milestone.", info_x,
              image_top - 170, info_w, 8.3, MUTED)
    caption_y = image_top - image_h - 15
    text(c, f"{data['width']} x {data['height']} pixels / MacBook Air / static PNG", margin, caption_y, 7.6, MUTED)
    label(c, f"DUE {due_label.upper()} / {due_time} {zone_label}", margin, caption_y - 22, INK, 8.1)

    band_top = caption_y - 37
    band_h = 58
    c.setFillColor(NAVY)
    c.roundRect(margin, band_top - band_h, usable, band_h, 7, fill=1, stroke=0)
    minutes = state.get("minutes")
    effort = f" / {minutes:g} MIN" if isinstance(minutes, (int, float)) and minutes > 0 else ""
    label(c, f"NEXT ACTION{effort}", margin + 13, band_top - 15, AMBER, 6.6)
    text(c, state["action"], margin + 13, band_top - 34, 12, IVORY)
    fallback_minutes = state.get("fallback_minutes")
    fallback_effort = (f" / {fallback_minutes:g} min"
                       if isinstance(fallback_minutes, (int, float)) and fallback_minutes > 0 else "")
    text(c, f"Busy day: {state['fallback']}{fallback_effort}",
         margin + 13, band_top - 48, 7.7, IVORY)

    stage_y = band_top - band_h - 25
    step = usable / total
    for idx, m in enumerate(stages):
        x = margin + idx * step
        c.setFillColor(AMBER if m["completed"] else IVORY)
        c.setStrokeColor(AMBER if m["completed"] else MUTED)
        c.circle(x + 5, stage_y + 3, 4.2, fill=1, stroke=1)
        text(c, m["name"], x + 15, stage_y, 8.4)
        text(c, "Recorded" if m["completed"] else "Pending", x + 15, stage_y - 13, 6.8, MUTED)

    schedule_top = stage_y - 38
    all_stages_done = completed == total
    label(c, "FINISHED WITH EVIDENCE" if all_stages_done else "FINISH WITH EVIDENCE", margin, schedule_top, INK)
    schedule = [
        ("17 NOV", "Verify",
         "Owner confirmed readable; no crop or overlap." if stage_status.get("Verify") else
         "Check the real lock screen; record overlap, crop and legibility.",
         "Done" if stage_status.get("Verify") else "10 min"),
        ("17 NOV" if stage_status.get("Package") else "18 NOV", "Package",
         "Accepted; final package checks are recorded." if stage_status.get("Package") else
         "Accept consistent files after device check; fixes only if needed.",
         "Done" if stage_status.get("Package") else "20 min"),
        ("19-20", "Reserve", "Available for new issues only; no compulsory work." if all_stages_done else
         "Conditional review/recovery only; no work if accepted early.", "0 min" if all_stages_done else "0-30 min"),
    ]
    row_top = schedule_top - 13
    for date, stage, action, effort in schedule:
        c.setStrokeColor(LINE)
        c.line(margin, row_top, w - margin, row_top)
        text(c, date, margin, row_top - 14, 7.5, MUTED)
        text(c, stage, margin + 55, row_top - 14, 8.4, INK)
        paragraph(c, action, margin + 125, row_top - 5, usable - 172, 7.6, INK, 10.5)
        text(c, effort, w - margin - 37, row_top - 14, 7.4, MUTED)
        row_top -= 31
    if all_stages_done:
        buffer_text = ("Accepted before the Nov 18 target. The original plan allowed 60 min/day, with no excluded "
                       "days assumed: 240 min across Nov 17-20, at most 90 min planned including conditional fixes "
                       "and reserve. Actual effort was not timed. No further project work is required unless an issue "
                       "appears. Manual Handshake submission is a separate next action.")
    else:
        buffer_text = ("Planning allowance: 60 min/day, no excluded days assumed; 240 min across 17-20 Nov. "
                       "30 min core + up to 30 min fixes on Nov 18 + up to 30 min reserve = at most 90 min; "
                       "150 min headroom. Finish any last check by 18:00 IST. After a missed day, carry the earliest "
                       "unfinished task forward. Fallbacks replace a session; they do not complete a milestone.")
    bottom = paragraph(c, buffer_text, margin, row_top - 2, usable, 7.6, MUTED, 10.6)

    section_top = bottom - 21
    label(c, "WHO MADE WHAT", margin, section_top, INK)
    origin = ("Gemini generated the original miniature workshop and developed the final countdown-project plan "
              "on 17 Nov. A specific follow-up repaired the buffer and effort totals; both actual responses "
              "and prompts are retained. ChatGPT coordinated that review, restored the local renderer, "
              "checked the date/status logic and typeset the current image.")
    bottom = paragraph(c, origin, margin, section_top - 10, usable, 8, INK, 11.2)

    section_top = bottom - 21
    label(c, "USE IT / REFRESH IT", margin, section_top, INK)
    device_sentence = ("The owner checked the installed layout: readable, no crop or overlap. "
                       "Final status/action text was refreshed locally; no installed screenshot exists. " if device_checked else
                       "The actual Mac lock-screen check remains open: inspect clock/control overlap, crop and legibility. ")
    use = (device_sentence + "Re-export when the date or evidence changes, then replace the image in Mac Wallpaper settings. "
           "Calendar-day differences use Asia/Kolkata: Due today before 20:00 on the deadline date; "
           "Deadline passed at/after cutoff unless completion is recorded. Public downloads were checked without sign-in. "
           "The PNG is static. Reminders remain off.")
    bottom = paragraph(c, use, margin, section_top - 10, usable, 8, INK, 11.2)
    assert bottom > 36, f"Summary overflows page: content bottom={bottom:.1f}"
    c.setStrokeColor(LINE)
    c.line(margin, 29, w - margin, 29)
    text(c, f"Project snapshot / {date_label} / Evidence governs status", margin, 17, 6.7, MUTED)
    c.save()
    print(json.dumps({"output": str(output), "manifest": str(manifest_path),
                      "as_of": state["as_of"], "days": state["calendar_days"],
                      "milestones_recorded": completed, "content_bottom_pt": round(bottom, 1)}))


if __name__ == "__main__":
    main()
