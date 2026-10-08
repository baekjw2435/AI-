"""Exercise the production KST schedule, persisted state, and admin commands."""
import ast
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import random
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


MAIN = Path(__file__).resolve().parents[1] / "main.py"
KST = timezone(timedelta(hours=9))


def schedule_namespace(env=None):
    """Load actual schedule definitions while excluding bot initialization."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    nodes = []
    in_schedule = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if "KST" in names:
                in_schedule = True
            if "CHO" in names:
                break
        if in_schedule:
            nodes.append(node)
    ns = {
        "os": os, "re": re, "json": json, "random": random,
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
        "STANDARD_LOOKUP_COMMANDS": ("!루트", "!탐색", "!중간벽"),
        "DICTIONARY_LOOKUP_COMMANDS": ("!공격", "!한방", "!장문", "!중간", "!종결"),
    }
    with patch.dict(os.environ, env or {}, clear=True):
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN), "exec"), ns)
    return ns


class LockScheduleTests(unittest.TestCase):
    def setUp(self):
        self.ns = schedule_namespace()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_path = Path(self.temp.name) / "lock_state.json"
        self.ns["LOCK_FILE"] = str(self.state_path)

    def load_state(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.ns["lock_load"]()

    def at(self, day, hour, minute=0):
        return self.ns["in_window"](datetime(2026, 10, day, hour, minute, tzinfo=KST))

    def test_default_enabled_schedule_replaces_legacy_environment_switches(self):
        ns = schedule_namespace({"STUDY_LOCK": "false", "STUDY_LOCK_HOURS": "1-2"})
        self.assertTrue(ns["LOCK"]["on"])
        self.assertEqual((ns["LOCK"]["start"], ns["LOCK"]["weekend_start"], ns["LOCK"]["end"]),
                         (18, 14, 24))
        self.assertEqual(ns["LOCK"]["schedule_version"], "kst-weekday-weekend-v1")

    def test_weekday_and_weekend_boundaries_are_half_open(self):
        # 2026-10-09 is Friday; 10/10 and 10/11 are the weekend.
        cases = ((9, 0, 0, False), (9, 17, 59, False), (9, 18, 0, True),
                 (9, 23, 59, True), (10, 0, 0, False), (10, 13, 59, False),
                 (10, 14, 0, True), (10, 23, 59, True), (11, 0, 0, False),
                 (11, 13, 59, False), (11, 14, 0, True), (11, 23, 59, True),
                 (12, 0, 0, False), (12, 17, 59, False), (12, 18, 0, True))
        for day, hour, minute, expected in cases:
            with self.subTest(day=day, hour=hour, minute=minute):
                self.assertEqual(self.at(day, hour, minute), expected)

    def test_utc_inputs_use_korean_date_and_time(self):
        cases = ((9, 8, 59, False), (9, 9, 0, True), (9, 14, 59, True),
                 (9, 15, 0, False), (10, 4, 59, False), (10, 5, 0, True),
                 (11, 14, 59, True), (11, 15, 0, False))
        for day, hour, minute, expected in cases:
            with self.subTest(day=day, hour=hour, minute=minute):
                now = datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)
                self.assertEqual(self.ns["in_window"](now), expected)

    def test_clock_is_read_with_kst_when_no_time_is_injected(self):
        class Clock:
            @staticmethod
            def now(zone):
                self.assertEqual(zone, KST)
                return datetime(2026, 10, 10, 14, 0, tzinfo=zone)
        self.ns["datetime"] = Clock
        self.assertTrue(self.ns["in_window"]())

    def test_legacy_disabled_saved_state_is_migrated_but_delay_is_preserved(self):
        self.load_state({"on": False, "start": 2, "end": 3, "dmin": 7, "dmax": 11})
        lock = self.ns["LOCK"]
        self.assertTrue(lock["on"])
        self.assertEqual((lock["start"], lock["weekend_start"], lock["end"]), (18, 14, 24))
        self.assertEqual((lock["dmin"], lock["dmax"]), (7, 11))
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["schedule_version"], self.ns["LOCK_SCHEDULE_VERSION"])
        self.assertTrue(saved["on"])

    def test_current_version_admin_changes_survive_restart(self):
        saved = {"schedule_version": self.ns["LOCK_SCHEDULE_VERSION"], "on": False,
                 "start": 19, "end": 23, "weekend_start": 15, "dmin": 5, "dmax": 9}
        self.load_state(saved)
        self.assertEqual(self.ns["LOCK"], saved)
        self.ns["lock_save"]()
        restarted = schedule_namespace({"STUDY_LOCK": "true"})
        restarted["LOCK_FILE"] = str(self.state_path)
        with redirect_stdout(io.StringIO()):
            restarted["lock_load"]()
        self.assertEqual(restarted["LOCK"], saved)

    def test_missing_and_corrupt_state_keep_new_schedule(self):
        for content in (None, "{broken", "[]"):
            with self.subTest(content=content):
                if self.state_path.exists():
                    self.state_path.unlink()
                if content is not None:
                    self.state_path.write_text(content, encoding="utf-8")
                with redirect_stdout(io.StringIO()):
                    self.ns["lock_load"]()
                self.assertTrue(self.ns["LOCK"]["on"])
                self.assertEqual((self.ns["LOCK"]["start"], self.ns["LOCK"]["weekend_start"],
                                  self.ns["LOCK"]["end"]), (18, 14, 24))

    def test_invalid_legacy_delay_does_not_disable_default_delay(self):
        self.load_state({"on": False, "dmin": 90, "dmax": 5})
        self.assertEqual((self.ns["LOCK"]["dmin"], self.ns["LOCK"]["dmax"]), (10, 15))
        self.assertTrue(self.ns["LOCK"]["on"])

    def test_valid_delay_environment_still_applies(self):
        ns = schedule_namespace({"STUDY_LOCK_DELAY": "4-8"})
        self.assertEqual((ns["LOCK"]["dmin"], ns["LOCK"]["dmax"]), (4, 8))

    def test_manual_off_does_not_change_calendar_window(self):
        self.ns["in_window"] = lambda: True
        self.assertTrue(self.ns["lock_now"]())
        self.ns["LOCK"]["on"] = False
        self.assertFalse(self.ns["lock_now"]())
        self.ns["LOCK"]["on"] = True
        self.ns["in_window"] = lambda: False
        self.assertFalse(self.ns["lock_now"]())

    def test_status_text_names_both_day_groups_and_midnight(self):
        text = self.ns["lock_window_text"]()
        for phrase in ("평일", "18시", "주말", "14시", "자정"):
            self.assertIn(phrase, text)


class LockCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = schedule_namespace()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ns["LOCK_FILE"] = str(Path(self.temp.name) / "lock_state.json")
        self.ns.update({
            "GUILD_ID": 0, "CHANNEL_ID": 0, "HUNMIN_CHANNELS": set(),
            "ENGLISH_CHANNELS": set(), "CHEMISTRY_CHANNEL_ID": -1,
            "mode_of": lambda channel: "표준", "lookup_channel_notice": lambda content, channel: None,
            "channel_role": lambda channel: ("study", "표준"),
            "GAMES": SimpleNamespace(get=lambda channel: None),
            "CHESS_READY": False, "OMOK_READY": False, "QUORIDOR_READY": False,
        })
        node = next(node for node in ast.parse(MAIN.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_message")
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(MAIN), "exec"), self.ns)

    def message(self, command, admin=True):
        return SimpleNamespace(content=command,
                               author=SimpleNamespace(id=123, bot=False,
                                                      guild_permissions=SimpleNamespace(administrator=admin)),
                               guild=SimpleNamespace(id=1, owner_id=99),
                               channel=SimpleNamespace(id=1544553748565729381, send=AsyncMock()))

    async def test_status_command_explains_weekday_and_weekend_schedule(self):
        msg = self.message("!제한", admin=False)
        await self.ns["on_message"](msg)
        text = msg.channel.send.await_args.args[0]
        for phrase in ("한국시간", "평일", "18시", "주말", "14시", "자정", "10~15초"):
            self.assertIn(phrase, text)

    async def test_admin_hours_command_still_sets_same_window_for_all_days(self):
        msg = self.message("!제한 20-23")
        await self.ns["on_message"](msg)
        self.assertEqual((self.ns["LOCK"]["start"], self.ns["LOCK"]["weekend_start"],
                          self.ns["LOCK"]["end"]), (20, 20, 23))
        saved = json.loads(Path(self.ns["LOCK_FILE"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["weekend_start"], 20)

    async def test_admin_off_and_on_persist_without_losing_schedule(self):
        for command, enabled in (("!제한 끄기", False), ("!제한 켜기", True)):
            with self.subTest(command=command):
                await self.ns["on_message"](self.message(command))
                self.assertEqual(self.ns["LOCK"]["on"], enabled)
                saved = json.loads(Path(self.ns["LOCK_FILE"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["on"], enabled)
                self.assertEqual((saved["start"], saved["weekend_start"], saved["end"]), (18, 14, 24))

    async def test_non_admin_cannot_disable_or_change_schedule(self):
        before = dict(self.ns["LOCK"])
        for command in ("!제한 끄기", "!제한 1-2", "!제한 딜레이 0-0"):
            with self.subTest(command=command):
                msg = self.message(command, admin=False)
                await self.ns["on_message"](msg)
                self.assertEqual(self.ns["LOCK"], before)
                self.assertIn("관리자", msg.channel.send.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
