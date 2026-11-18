"""Focused checks for date boundaries, progress honesty, and export inputs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from renderer.render import ConfigError, cover_image, device_mockup, instant, render_wallpaper, state_at, validate_config


class CountdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "art.png").write_bytes(b"test fixture; date tests never decode this")
        (self.base / "evidence.txt").write_text("Test fixture only")
        self.raw = {
            "goal": "Publish one useful case study", "title": "PROOF OF WORK",
            "subtitle": "My AI Portfolio Launch", "deadline": "2026-11-20T20:00:00+05:30",
            "timezone": "Asia/Kolkata", "artwork": "art.png", "width": 1080, "height": 2400,
            "device_validated": False, "artwork_provenance": {"provider": "Google Gemini", "evidence": "evidence.txt"},
            "milestones": [{"name": n, "completed": False, "evidence": None} for n in ("Scope", "Reproduce", "Evaluate", "Explain", "Publish")],
            "tasks": [{"date": "2026-11-19", "action": "Check the links", "fallback": "Check one link", "minutes": 25, "fallback_minutes": 5}],
            "default_action": "Review the next unfinished step", "default_fallback": "Write the next step",
            "completion": {"recorded": False, "evidence": None}}
        self.config = validate_config(self.raw, self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, at):
        return state_at(self.config, instant(at, "test time"))

    def test_calendar_days_several_days_and_day_before(self):
        self.assertEqual(self.state("2026-11-15T23:59:59+05:30")["headline"], "5")
        self.assertEqual(self.state("2026-11-19T23:59:59+05:30")["headline"], "1")
        self.assertEqual(self.state("2026-11-19T23:59:59+05:30")["action"], "Check the links")

    def test_deadline_day_before_immediately_before_at_and_after(self):
        for time in ("00:00:00", "12:00:00", "19:59:59.999999"):
            self.assertEqual(self.state(f"2026-11-20T{time}+05:30")["headline"], "Due today")
        for at in ("2026-11-20T20:00:00+05:30", "2026-11-20T20:00:00.000001+05:30", "2026-11-21T01:00:00+05:30"):
            self.assertEqual(self.state(at)["headline"], "Deadline passed")
            self.assertFalse(self.state(at)["completion_recorded"])

    def test_timezone_utc_equivalence_and_midnight(self):
        self.assertEqual(self.state("2026-11-19T18:29:59Z")["headline"], "1")
        self.assertEqual(self.state("2026-11-19T18:30:00Z")["headline"], "Due today")
        self.assertEqual(self.state("2026-11-20T14:29:59Z")["headline"], "Due today")
        self.assertEqual(self.state("2026-11-20T14:30:00Z")["headline"], "Deadline passed")
        self.assertEqual(self.state("2026-11-20T14:30:00Z"), self.state("2026-11-20T20:00:00+05:30"))
        utc_config = copy.deepcopy(self.raw)
        utc_config["deadline"] = "2026-11-20T14:30:00Z"
        validated = validate_config(utc_config, self.base)
        at = instant("2026-11-20T19:59:59+05:30", "as_of")
        self.assertEqual(state_at(validated, at), state_at(self.config, at))

    def test_missed_task_and_time_do_not_update_progress(self):
        before = copy.deepcopy(self.config["milestones"])
        self.state("2026-11-19T18:00:00+05:30")
        after = self.state("2026-11-21T18:00:00+05:30")
        self.assertEqual(self.config["milestones"], before)
        self.assertEqual(after["milestones"], before)
        self.assertEqual(after["completed_milestones"], 0)

    def test_completion_requires_explicit_evidence_and_does_not_infer_milestones(self):
        self.raw["completion"] = {"recorded": True, "evidence": "evidence.txt"}
        c = validate_config(self.raw, self.base)
        s = state_at(c, instant("2026-11-21T12:00:00+05:30", "as_of"))
        self.assertEqual(s["headline"], "Published")
        self.assertEqual(s["completed_milestones"], 0)
        self.raw["completion"]["evidence"] = None
        with self.assertRaises(ConfigError):
            validate_config(self.raw, self.base)

    def test_completed_project_keeps_countdown_and_ledger_across_cutoff(self):
        names = ["Plan", "Design", "Build", "Verify", "Package"]
        self.raw.update(milestone_order=names, completion_headline="Launched",
                        completion_action="Submit manually on Handshake",
                        completion_fallback="Review the cover and description",
                        completion_minutes=10, completion_fallback_minutes=5,
                        daily_capacity_minutes=60)
        self.raw["milestones"] = [{"name": name, "completed": True, "evidence": "evidence.txt"}
                                  for name in names]
        self.raw["completion"] = {"recorded": True, "evidence": "evidence.txt"}
        raw_before = copy.deepcopy(self.raw)
        c = validate_config(self.raw, self.base)
        ledger_before = copy.deepcopy(c)
        cases = (
            ("2026-11-17T12:00:00+05:30", "3", "DAYS TO DEADLINE"),
            ("2026-11-19T23:59:59+05:30", "1", "DAY TO DEADLINE"),
            ("2026-11-20T00:00:00+05:30", "Due today", "BEFORE THE CUTOFF"),
            ("2026-11-20T19:59:59.999999+05:30", "Due today", "BEFORE THE CUTOFF"),
            ("2026-11-20T20:00:00+05:30", "Launched", "COMPLETION RECORDED"),
            ("2026-11-20T20:00:00.000001+05:30", "Launched", "COMPLETION RECORDED"),
            ("2026-11-21T12:00:00+05:30", "Launched", "COMPLETION RECORDED"),
        )
        for at, headline, caption in cases:
            with self.subTest(at=at):
                state = state_at(c, instant(at, "as_of"))
                self.assertEqual((state["headline"], state["caption"]), (headline, caption))
                self.assertEqual(state["completed_milestones"], 5)
                self.assertTrue(state["completion_recorded"])
                self.assertEqual(state["action"], "Submit manually on Handshake")
                self.assertEqual(state["fallback"], "Review the cover and description")
                self.assertEqual((state["minutes"], state["fallback_minutes"]), (10, 5))
                self.assertIsNone(state["selected_task_date"])
                self.assertFalse(state["carried_forward"])
        self.assertEqual(state_at(c, instant("2026-11-20T14:30:00Z", "as_of")),
                         state_at(c, instant("2026-11-20T20:00:00+05:30", "as_of")))
        state["milestones"][0]["completed"] = False
        self.assertEqual(c, ledger_before)
        self.assertEqual(self.raw, raw_before)

    def test_completion_effort_is_optional_and_validated(self):
        self.raw["completion"] = {"recorded": True, "evidence": "evidence.txt"}
        at = instant("2026-11-17T12:00:00+05:30", "as_of")
        state = state_at(validate_config(self.raw, self.base), at)
        self.assertIsNone(state["minutes"])
        self.assertIsNone(state["fallback_minutes"])
        for field in ("completion_minutes", "completion_fallback_minutes"):
            for value in (None, True, 0, -1, "10", 1.5):
                bad = copy.deepcopy(self.raw)
                bad[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ConfigError):
                    validate_config(bad, self.base)
            bad = copy.deepcopy(self.raw)
            bad.update(daily_capacity_minutes=60)
            bad[field] = 61
            with self.subTest(field=field, case="capacity"), self.assertRaises(ConfigError):
                validate_config(bad, self.base)
        bad = copy.deepcopy(self.raw)
        bad.update(completion_minutes=5, completion_fallback_minutes=10)
        with self.assertRaises(ConfigError):
            validate_config(bad, self.base)

    def test_invalid_essentials_offsets_evidence_and_sample(self):
        for key, value in (("deadline", None), ("deadline", "2026-11-20T20:00:00"),
                           ("timezone", "Mars/Olympus"),
                           ("width", None), ("device_validated", None)):
            bad = copy.deepcopy(self.raw)
            bad[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                validate_config(bad, self.base)
        self.raw["milestones"][0]["completed"] = True
        with self.assertRaises(ConfigError):
            validate_config(self.raw, self.base)
        self.raw["milestones"][0]["completed"] = False
        self.raw["sample"] = True
        with self.assertRaises(ConfigError):
            validate_config(self.raw, self.base)
        self.assertTrue(validate_config(self.raw, self.base, preview=True)["sample"])

    def test_render_all_boundary_headlines_and_mockup_dimensions(self):
        from PIL import Image
        Image.new("RGB", (1080, 2400), "#0A1424").save(self.base / "art.png")
        self.config["sample"] = True
        for at in ("2026-11-04T12:00:00+05:30", "2026-11-19T12:00:00+05:30",
                   "2026-11-20T12:00:00+05:30", "2026-11-20T20:00:00+05:30"):
            with self.subTest(at=at):
                image = render_wallpaper(self.config, self.state(at), preview=True)
                self.assertEqual(image.size, (1080, 2400))
                self.assertEqual(image.mode, "RGB")
        mockup = device_mockup(image, self.config)
        self.assertEqual(mockup.size, (1200, 1500))

    def test_malformed_nested_objects_raise_config_errors(self):
        for field, value in (("fonts", []), ("fonts", "bad"), ("fonts", None),
                             ("artwork_provenance", []), ("artwork_provenance", None),
                             ("tasks", [None]), ("milestones", self.raw["milestones"] + [None]),
                             ("milestones", [None] + self.raw["milestones"][1:]), ("sample", "false")):
            c = copy.deepcopy(self.raw)
            c[field] = value
            for preview in (True, False):
                with self.subTest(field=field, value=value, preview=preview), self.assertRaises(ConfigError):
                    validate_config(c, self.base, preview=preview)

    def test_short_portrait_countdown_fits_above_caption(self):
        from PIL import Image, ImageDraw
        from renderer.render import font
        Image.new("RGB", (1080, 1620), "#0A1424").save(self.base / "art.png")
        self.config["height"] = 1620
        state = self.state("2026-11-04T12:00:00+05:30")
        state["headline"] = "888"
        image = render_wallpaper(self.config, state, preview=True)
        self.assertEqual(image.size, (1080, 1620))
        draw = ImageDraw.Draw(image)
        f = font(self.config, min(188, .078 * 1620), True)
        bounds = draw.textbbox((0, .303 * 1620), "888", font=f, anchor="lt")
        self.assertLess(bounds[3] + 10, .386 * 1620)

    def test_missed_work_carries_forward_and_milestone_gates_downstream(self):
        self.raw["tasks"] = [
            {"id": "scope", "date": "2026-11-04", "action": "Find the source repo", "fallback": "Write its name", "minutes": 20, "fallback_minutes": 5},
            {"id": "run", "date": "2026-11-05", "action": "Run the baseline", "fallback": "Check the entrypoint", "minutes": 30, "fallback_minutes": 5,
             "depends_on": ["scope"], "requires_milestones": ["Scope"]}]
        at = instant("2026-11-07T12:00:00+05:30", "as_of")
        c = validate_config(self.raw, self.base)
        state = state_at(c, at)
        self.assertEqual(state["action"], "Find the source repo")
        self.assertTrue(state["carried_forward"])
        self.assertEqual(state["selected_task_date"], "2026-11-04")
        self.raw["tasks"][0].update(completed=True, evidence="evidence.txt")
        state = state_at(validate_config(self.raw, self.base), at)
        self.assertEqual(state["action"], "Review Scope evidence before continuing")
        self.assertEqual(state["completed_milestones"], 0)
        self.raw["milestones"][0].update(completed=True, evidence="evidence.txt")
        state = state_at(validate_config(self.raw, self.base), at)
        self.assertEqual(state["action"], "Run the baseline")
        self.assertEqual(state["completed_milestones"], 1)

    def test_dependency_errors_and_capacity_overload_are_rejected(self):
        for fields in ({"depends_on": ["missing"]}, {"id": "self", "depends_on": ["self"]},
                       {"depends_on": "wrong"}, {"requires_milestones": ["Imaginary"]}, {"completed": True}):
            c = copy.deepcopy(self.raw)
            c["tasks"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ConfigError):
                validate_config(c, self.base)
        c = copy.deepcopy(self.raw)
        c["daily_capacity_minutes"] = 20
        with self.assertRaises(ConfigError):
            validate_config(c, self.base)

    def test_landscape_export_keeps_native_interface_areas_clear(self):
        from PIL import Image
        Image.new("RGB", (2560, 1664), "#0A1424").save(self.base / "art.png")
        self.raw.update(layout="landscape", width=2560, height=1664)
        c = validate_config(self.raw, self.base)
        for at in ("2026-11-04T12:00:00+05:30", "2026-11-19T12:00:00+05:30",
                   "2026-11-20T19:59:59+05:30", "2026-11-20T20:00:00+05:30"):
            state = state_at(c, instant(at, "as_of"))
            image = render_wallpaper(c, state)
            self.assertEqual(image.size, (2560, 1664))
            # Uniform source should remain uniform where the real clock and controls belong.
            self.assertEqual(image.getpixel((1500, 250)), (10, 20, 36))
            self.assertEqual(image.getpixel((1700, 1550)), (10, 20, 36))
        self.assertEqual(device_mockup(image, c).size, (1500, 1100))
        self.assertEqual(cover_image(image, c, state).size, (1500, 1000))

    def test_countdown_project_scope_progress_and_completion_copy(self):
        names = ["Plan", "Design", "Build", "Verify", "Package"]
        self.raw.update(goal="Deliver the countdown project", subtitle="My Countdown Project Launch",
                        milestone_order=names, completion_headline="Launched",
                        completion_action="Review the delivered countdown package",
                        completion_fallback="Save one lesson learned",
                        deadline_passed_action="Review the countdown project and reset its deadline")
        self.raw["milestones"] = [{"name": name, "completed": i < 3,
                                    "evidence": "evidence.txt" if i < 3 else None} for i, name in enumerate(names)]
        self.raw["tasks"] = [{"date": "2026-11-05", "action": "Check the wallpaper on my Mac", "fallback": "Note one overlap or readability issue",
                              "minutes": 10, "fallback_minutes": 5, "requires_milestones": names[:3]}]
        c = validate_config(self.raw, self.base)
        current = state_at(c, instant("2026-11-05T00:05:00+05:30", "as_of"))
        self.assertEqual(current["headline"], "15")
        self.assertEqual(current["completed_milestones"], 3)
        self.assertEqual(current["action"], "Check the wallpaper on my Mac")
        self.assertEqual(current["minutes"], 10)
        self.assertEqual(current["fallback_minutes"], 5)
        missed = state_at(c, instant("2026-11-19T12:00:00+05:30", "as_of"))
        self.assertEqual(missed["action"], current["action"])
        self.assertEqual(missed["completed_milestones"], 3)
        cutoff = state_at(c, instant("2026-11-20T20:00:00+05:30", "as_of"))
        self.assertEqual(cutoff["headline"], "Deadline passed")
        self.assertEqual(cutoff["action"], "Review the countdown project and reset its deadline")
        self.assertEqual(cutoff["completed_milestones"], 3)
        self.assertFalse(cutoff["carried_forward"])
        self.assertIsNone(cutoff["selected_task_date"])
        self.raw["completion"] = {"recorded": True, "evidence": "evidence.txt"}
        launched = state_at(validate_config(self.raw, self.base), instant("2026-11-21T12:00:00+05:30", "as_of"))
        self.assertEqual(launched["headline"], "Launched")
        self.assertEqual(launched["action"], "Review the delivered countdown package")
        self.assertNotIn("case study", str(launched))
        self.assertNotIn("repo", str(launched))

    def test_invalid_custom_milestone_order_is_rejected(self):
        for order in (None, "Plan", {}, ["Plan"], ["Plan"] * 5, ["Plan", "Design", "Build", "Verify", ""]):
            c = copy.deepcopy(self.raw)
            c["milestone_order"] = order
            with self.subTest(order=order), self.assertRaises(ConfigError):
                validate_config(c, self.base)


if __name__ == "__main__":
    unittest.main()
