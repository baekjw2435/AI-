"""Exercise the real standard training path without creating a Discord client."""

import ast
import contextlib
import glob
import heapq
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import game as gm
import route_engine as rq


ROOT = Path(__file__).resolve().parents[1]


def load_standard_training_functions():
    """Load production functions and data; omit main.py's client and startup calls."""
    source = ROOT / "main.py"
    functions = {
        "dec", "dueum", "syllable_keys", "is_self_loop", "find_file",
        "load_standard_words", "load_route_learning", "legal_candidates",
        "game_dictionary", "run_bot_turn",
    }
    constants = {
        "MODE_STANDARD", "MODE_COMPLEX", "STD_LONGEST", "STD_ENDWORDS", "STD_STARTCOUNT",
        "STD_FIRST", "STD_ONESHOT", "STD_ATTACK", "STD_DOLLIM_END", "STD_FIRSTWORDS",
        "STD_READY", "STD_MID_ROOT_SYLLABLES", "STD_MID_ROOT_TARGETS", "STD_MID_ROOT_LINKS",
        "ROUTE_CORE", "ROUTE_READY",
    }
    nodes = []
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants for target in node.targets
        ):
            nodes.append(node)
    namespace = {"gm": gm, "rq": rq, "glob": glob, "heapq": heapq, "json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    previous_directory = os.getcwd()
    try:
        os.chdir(ROOT)
        with contextlib.redirect_stdout(io.StringIO()):
            namespace["load_standard_words"]()
            namespace["load_route_learning"]()
    finally:
        os.chdir(previous_directory)
    return namespace


class StandardTrainingTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_standard_training_functions()

    def setUp(self):
        self.assertTrue(self.app["ROUTE_READY"])
        self.dictionary = self.app["game_dictionary"](self.app["MODE_STANDARD"])
        self.app["GAMES"] = gm.GameRegistry()
        self.app["asyncio"] = SimpleNamespace(sleep=AsyncMock())
        self.app["schedule_turn_timeout"] = AsyncMock()
        self.channel = SimpleNamespace(id=1544722279349485578, send=AsyncMock())

    def game(self, current="족", shield=0):
        game = gm.Game(self.channel.id, self.dictionary, [None, 123], ["훈련봇", "참가자"], current)
        game.shield = shield
        self.app["GAMES"].put(game)
        return game

    def test_training_and_explorer_share_loaded_v127_core(self):
        core = self.app["ROUTE_CORE"]
        self.assertIs(self.dictionary.core, core)
        self.assertEqual(rq.ENGINE_VERSION, "1.27")
        self.assertEqual(core.learning.player_selection["version"], rq.PLAYER_SELECTION_VERSION)
        self.assertEqual(core.recent.player_selection["version"], rq.PLAYER_SELECTION_VERSION)
        self.assertEqual(core.flow.policy["playerSelection"]["version"], rq.PLAYER_SELECTION_VERSION)
        self.assertEqual(core.flow.policy["historyPolicyVersion"], rq.FLOW_HISTORY_POLICY_VERSION)
        self.assertEqual(core.flow.policy["maxHistory"], 12)
        history = [("족지족", 0, "족"), ("족족", 0, "족")]
        used = {word for word, _shield, _current in history}
        rows = self.app["legal_candidates"]("족", 0, used, history)
        word, _note = self.dictionary.bot_move("족", 0, used, history)
        self.assertEqual(word, rows[0]["word"])
        self.assertEqual((word, rows[0]["recommendationScore"]), ("족제비업", 42.7))
        rare = next(row for row in rows if row["word"] == "족사부착쇄조개")
        self.assertGreater(rows[0]["recommendationScore"], rare["recommendationScore"])
        self.assertEqual(rows[0]["flowRanking"]["availableCount"], 2)

    async def test_main_bot_turn_passes_game_history_and_applies_v127_recommendation(self):
        game = self.game()
        game.apply("족지족")
        game.apply("족족")
        captured = {}
        original = self.dictionary.bot_move

        def record_and_choose(current, shield, used, history):
            captured.update(current=current, shield=shield, used=set(used), history=list(history))
            return original(current, shield, used, history)

        with patch.object(self.dictionary, "bot_move", side_effect=record_and_choose):
            await self.app["run_bot_turn"](game, self.channel)
        self.assertEqual(captured, {
            "current": "족", "shield": 0, "used": {"족지족", "족족"},
            "history": [("족지족", 0, ""), ("족족", 0, "")],
        })
        self.assertEqual(game.history[-1][0], "족제비업")
        self.assertEqual(game.used, {"족지족", "족족", "족제비업"})
        self.assertEqual((game.current, game.shield, game.turn), ("업", 0, 1))
        self.assertFalse(game.finished)
        self.channel.send.assert_awaited_once()
        self.assertIn("족제비업", self.channel.send.await_args.kwargs["embed"].description)
        self.app["schedule_turn_timeout"].assert_awaited_once_with(game, self.channel)

    async def test_training_uses_all_twelve_supported_moves_and_keeps_real_word(self):
        game = self.game("법")
        words = ["법신덕", "덕업", "업업", "업시름", "늠률", "율무죽", "죽지뼈",
                 "뼈살촉", "촉촉", "촉탁살인죄", "죄율", "율자죽"]
        for word in words:
            game.apply(word)
        original = rq.flow_context
        with patch.object(rq, "flow_context", wraps=original) as context:
            await self.app["run_bot_turn"](game, self.channel)
        self.assertEqual([move[0] for move in context.call_args.args[3]], words)
        self.assertIsNotNone(context.call_args.kwargs["playable"])
        self.assertEqual(game.history[-1][0], "죽을죄")
        self.assertIn("죽을죄", self.channel.send.await_args.kwargs["embed"].description)

    def test_training_excludes_used_recommendation_and_preserves_protection(self):
        history = [("족지족", 0, "족"), ("족족", 0, "족")]
        used = {"족지족", "족족", "족제비업"}
        for shield in range(13):
            with self.subTest(shield=shield):
                word, _note = self.dictionary.bot_move("족", shield, used, history)
                self.assertIsNotNone(word)
                self.assertNotIn(word, used)
                self.assertIsNone(self.dictionary.legal(word, "족", shield, used))
                self.assertGreaterEqual(self.dictionary.follow_count(word[-1], used | {word}), shield)
                rows = self.app["legal_candidates"]("족", shield, used, history)
                self.assertEqual(word, rows[0]["word"])

    def test_training_rejects_a_real_one_shot_when_shield_remains(self):
        word = next(word for word in sorted(self.dictionary.core.one_shots)
                    if self.dictionary.has(word) and self.dictionary.follow_count(word[-1], {word}) == 0)
        self.assertIsNone(self.dictionary.legal(word, word[0], 0, set()))
        self.assertIn("보호막", self.dictionary.legal(word, word[0], 1, set()))
        chosen, _note = self.dictionary.bot_move(word[0], 1, set(), [])
        self.assertNotEqual(chosen, word)
        if chosen is not None:
            self.assertIsNone(self.dictionary.legal(chosen, word[0], 1, set()))

    def test_training_keeps_confirmed_wall_four_and_five_lines(self):
        for shield, expected in {
            5: ["벽바닥", "닥닥", "닥터스톱", "톱스핀", "핀우그리아어족"],
            4: ["벽탑", "탑승객", "객관적도덕", "덕업"],
        }.items():
            with self.subTest(shield=shield):
                game = self.game("벽", shield)
                for expected_word in expected:
                    history = [(w, sh, "") for w, sh, _who, _note in game.history]
                    word, note = self.dictionary.bot_move(game.current, game.shield, game.used, history)
                    self.assertEqual(word, expected_word)
                    self.assertIsNone(self.dictionary.legal(word, game.current, game.shield, game.used))
                    game.apply(word, note)
                self.assertEqual(game.shield, 0)
                self.assertEqual([row[0] for row in game.history], expected)

    def test_training_uses_standard_dueum_without_extra_conversion(self):
        self.assertIsNone(self.dictionary.legal("율무죽", "률", 0, set()))
        self.assertIsNone(self.dictionary.legal("늠률", "름", 0, set()))
        self.assertTrue(self.dictionary.has("넘나물"))
        self.assertIsNotNone(self.dictionary.legal("넘나물", "럼", 0, set()))
        self.assertNotIn("넘나물", self.dictionary.candidates("럼", set()))

    async def test_exhausted_state_finishes_instead_of_reusing_a_word(self):
        game = self.game()
        game.used.update(self.dictionary.candidates("족", set()))
        await self.app["run_bot_turn"](game, self.channel)
        self.assertTrue(game.finished)
        self.assertEqual(game.winner, 1)
        self.assertEqual(game.history, [])
        self.assertIsNone(self.app["GAMES"].get(game.channel_id))
        self.channel.send.assert_awaited_once()
        self.app["schedule_turn_timeout"].assert_not_awaited()

    def test_training_is_unavailable_if_current_core_failed_to_load(self):
        with patch.dict(self.app, {"ROUTE_READY": False}):
            self.assertIsNone(self.app["game_dictionary"](self.app["MODE_STANDARD"]))

    def test_loader_rejects_stale_flow_before_claiming_v127_readiness(self):
        core = self.app["ROUTE_CORE"]
        invalid = [
            {**core.flow.policy, "maxHistory": 8},
            {key: value for key, value in core.flow.policy.items() if key != "historyPolicyVersion"},
            {**core.flow.policy, "historyPolicyVersion": "older-policy"},
            {**core.flow.policy, "supportedHistory": 12},
            {**core.flow.policy, "longHistoryMinimumMoves": 2},
            {**core.flow.policy, "longHistoryMinimumMatches": 2},
        ]
        for policy in invalid:
            with self.subTest(policy=policy):
                output = io.StringIO()
                with patch.dict(self.app, {"ROUTE_CORE": core, "ROUTE_READY": True,
                                          "find_file": lambda patterns: str(ROOT / patterns[0])}), \
                        patch.object(rq, "load_learning", side_effect=lambda path:
                                     core.recent if "recent" in path else core.learning), \
                        patch.object(rq, "load_flow", return_value=SimpleNamespace(policy=policy)), \
                        contextlib.redirect_stdout(output):
                    self.app["load_route_learning"]()
                    self.assertFalse(self.app["ROUTE_READY"])
                    self.assertIsNone(self.app["ROUTE_CORE"])
                    self.assertIsNone(self.app["game_dictionary"](self.app["MODE_STANDARD"]))
                self.assertIn("12수 문맥 정책", output.getvalue())
                self.assertNotIn("자료 준비 완료", output.getvalue())

    def test_version_label_only_marks_standard_bot_training(self):
        training = self.game()
        footer = training.board().footer.text
        self.assertIn("표준 훈련 v1.27", footer)
        self.assertIn("훈련봇", footer)
        self.assertIn("참가자", footer)
        self.assertNotIn("순위전 전용", footer)
        self.assertFalse(any(name in footer for name in rq.MASTER_NAMES))
        pvp = gm.Game(self.channel.id, self.dictionary, [123, 456], ["참가자 A", "참가자 B"], "족")
        self.assertEqual(pvp.board().footer.text,
                         "표준 사전 · 표준두음법칙 적용 · 🔵 참가자 A · 🔴 참가자 B")
        complex_dictionary = gm.Dictionary("복합", set(), {}, {})
        complex_game = gm.Game(self.channel.id, complex_dictionary, [None, 123], ["훈련봇", "참가자"], "족")
        self.assertEqual(complex_game.board().footer.text,
                         "복합 사전 · 표준두음법칙 적용 · 🔵 훈련봇 · 🔴 참가자")


if __name__ == "__main__":
    unittest.main()
