# Static wallpaper exporter

The active project is **PROOF OF WORK — My Countdown Project Launch**. It counts down to 20 November 2026 at 20:00 Asia/Kolkata and tracks Plan, Design, Build, Verify, and Package. The renderer also retains legacy portrait vocabulary for backwards compatibility.

This exporter creates a static PNG. It does not install wallpapers, change device settings, run in the background, or configure reminders.

From the project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python renderer/render.py config/project.json --output exports/current
```

For an explicitly illustrative example or future date:

```sh
.venv/bin/python renderer/render.py config/project.json --as-of 2026-11-19T20:00:00+05:30 --preview --output exports/dated-preview
```

The command writes the full PNG, a reduced preview, a **generic device mockup**, a 1500×1000 presentation cover, and an audit manifest. The landscape cover presents the original workshop artwork with the project title and deadline; the separate mockup is not an installed-device screenshot. A sample configuration requires `--preview` and is visibly labeled with an example-deadline notice. A future date also requires `--preview`. The exporter stops on missing essentials or text too long to fit legibly. Source configuration is never changed by an export.

## Configuration

Paths resolve relative to the JSON configuration file. Set the real goal, title, subtitle, `deadline` (ISO 8601 with explicit UTC offset), `timezone` (IANA name such as `Asia/Kolkata`), original `artwork` path, `width`, `height`, and explicit `device_validated` boolean. `layout` is `landscape` or `portrait`; it is inferred from dimensions if absent. Portrait supports height/width ratios from 1.5 to 2.6, landscape from 0.45 to 0.85. The current Mac project uses the system-reported native **2560×1664** dimensions. `device_validated: false` records that the actual lock screen, native clock, controls and crop still require an installed-device view. Confirmed pixel resolution does not prove native-interface fit.

`milestone_order` defines five distinct stage names; `milestones` must match that order, each with a `completed` boolean and `evidence` path when complete. The active stages are Plan, Design, Build, Verify, Package; the current configuration and its linked evidence record their status. If no custom order is supplied, the historical portrait configuration retains Scope, Reproduce, Evaluate, Explain, Publish. The separate `completion` object records actual goal completion with evidence. The exporter never marks milestones complete as time passes; the count means recorded completion evidence, not elapsed time. Completion of the countdown project does not claim that the separate Handshake entry has been submitted.

Each dated `tasks` entry contains `date` (`YYYY-MM-DD`), `action`, `fallback`, positive `minutes`, and positive `fallback_minutes` no greater than the normal effort. Dates are unique. Optional `daily_capacity_minutes` prevents tasks exceeding the recorded capacity. The current plan allows 60 minutes per day and schedules shorter tasks to retain recovery time; no unavailable days were supplied.

Each task may also contain `id` (defaults to its date), `completed` (defaults to false), an `evidence` file when complete, `depends_on` (task IDs), and `requires_milestones` (verified stage names). References, cycles, future prerequisites and missing completion evidence are rejected. Active daily actions are copied from `config/daily-actions.json` into `config/project.json`; a package handoff must respect the Verify stage gate.

The next action is the **earliest unfinished task due on or before the countdown date**. A missed verification day therefore continues to show verification instead of jumping to package completion. If that task is blocked by a stage still awaiting evidence, the screen asks for that stage's evidence. Update the task's completion and evidence only after actual work; separately record a milestone when its acceptance criteria are met. Passing time changes neither ledger. If no unfinished task is due, the explicit `default_action` and `default_fallback` apply. At or after an uncompleted deadline, the next action becomes review and replanning. Optional `completion_headline`, `completion_action`, `completion_fallback`, `deadline_passed_action`, and `deadline_passed_fallback` keep these states tied to the actual goal. The landscape cover uses the configured title, subtitle and deadline; the historical portrait cover also supports `cover_message`.

When completion is recorded, `completion_action` and `completion_fallback` replace the task action, even before the deadline. They can identify a separate follow-up such as manual Handshake submission. Optional `completion_minutes` and `completion_fallback_minutes` supply its effort estimates. Each supplied value must be a positive integer within the daily capacity; when both are supplied, the fallback cannot exceed the normal effort. Omitted estimates remain `null` in the export manifest, so consumers should omit their effort labels rather than print a missing value.

Final exports require `artwork_provenance.provider` set to `Google Gemini` and an existing evidence file at `artwork_provenance.evidence`. The exporter checks these records and hashes the original asset; the human preparing the package must verify the actual generation provenance. It cannot determine image authorship from pixels.

Use `sample: true` only for a provisional example. Keep unknown real configuration values empty; final export will stop instead of guessing them. Do not set `device_validated: true` until the actual device has been inspected.

## Countdown convention

Remaining days are the difference between calendar dates in the named timezone, not rounded 24-hour durations. The countdown remains visible before the deadline even when actual project completion has been recorded; its numeric caption then reads **DAYS TO DEADLINE** (singular for one day). The completed milestone count stays separate. On the local deadline date before the cutoff, the headline is **Due today**. At the exact cutoff and afterward, it is **Deadline passed** without recorded completion, or the configured completion headline, **Launched** for this project, with evidence-backed completion. Zero remaining days does not imply success. The deadline instant is converted into the named zone for display and calendar arithmetic. `--as-of` also requires an explicit offset; equivalent UTC and local instants produce the same state, including when the deadline itself is stored in UTC.

The footer explicitly identifies the **countdown as-of time**. Milestones and task completion use the current recorded ledger; changing `--as-of` is not a historical reconstruction. Dated previews keep these records unchanged and are visibly labeled. The manifest records this distinction, the selected task's original date, whether it was carried forward, and any unmet prerequisite.

## Refresh and installation

Run the export command again on each day you want an updated image, then manually replace the wallpaper using the target device's normal wallpaper controls. Update dated tasks after reviewing the plan; record milestone completion only with evidence. A missed day changes neither the progress ledger nor the completion state. Verify the crop and real clock/widgets/notifications on the actual device before calling the fit validated.

For the landscape Mac layout, text is confined to the left, with the top center kept clear for the real clock and the bottom center kept clear for account controls. The target date and time sit beside numeric days in larger ivory/amber type; wider deadline-state words use a separate date row. The complete workshop image is contained without stretching or cropping its objects; softly blurred padding and narrow fades over quiet edges blend it into the target ratio. A smooth navy field supports left text. The source artwork and its watermark are retained. The half-size 1280×832 preview is a readability check, not evidence of actual macOS scaling or installation.

The portrait layout reserves the top 27% for the device interface, places countdown/action around 30–58%, and places progress/dates around 81–92%. Exact margins in both layouts remain estimates until the real lock screen is inspected. Shorten overlong actions rather than reducing critical text excessively.

## Fonts and checks

The included variable Lexend font is from the official [Google Fonts repository](https://github.com/google/fonts/tree/main/ofl/lexend), distributed under the included SIL Open Font License in `fonts/OFL.txt`. This avoids relying on fonts installed on a particular computer. Optional `fonts.regular` and `fonts.bold` paths replace it.

```sh
.venv/bin/python -m unittest renderer.test_render -v
```

These checks cover calendar-date boundaries, UTC equivalence, immediately before/at/after cutoff, missing/malformed inputs, missed-task recovery, prerequisite gates, capacity overload, evidence requirements, and both render layouts. Actual artwork readability and native-device overlap still require visual inspection.
