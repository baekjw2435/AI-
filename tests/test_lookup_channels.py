"""Exercise actual dispatch and interaction guards without starting Discord."""
import ast
import asyncio
from pathlib import Path
import random
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord


class LookupChannelTests(unittest.IsolatedAsyncioTestCase):
    STANDARD = 1544553748565729381
    COMPLEX = 1523328035686846495
    TRAINING = {1544722279349485578: "표준", 1544854625755209758: "복합"}
    ARENAS = {1544722084561817650: "표준", 1544854290819059765: "복합"}
    RENDERERS = ("embed_analysis", "embed_hanbang", "embed_jangmun", "embed_jangmun_end",
                 "embed_mid", "jonggyeol_embeds", "embed_route")
    SHARED = {
        "!공격 기": "embed_analysis", "!한방 기": "embed_hanbang",
        "!장문 기": "embed_jangmun", "!장문종결 기": "embed_jangmun_end",
        "!중간 기": "embed_mid", "!종결 기": "jonggyeol_embeds",
    }

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            "MODE_STANDARD", "MODE_COMPLEX", "ARENA", "TRAINING", "STUDY", "CHESS", "OMOK", "QUORIDOR",
            "LOOKUP_CHANNELS", "STANDARD_LOOKUP_COMMANDS", "DICTIONARY_LOOKUP_COMMANDS", "LOOKUP_COMMANDS",
            "CHANNEL_ROLES", "LOCK_COMMANDS_ALWAYS", "LOCK_COMMANDS_STANDARD", "LOCK_COMMANDS",
        }
        functions = {"channel_role", "mode_of", "lookup_channel_notice", "first_syllable", "dec", "on_message"}
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
                nodes.append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
                node.decorator_list = []
                nodes.append(node)
            if isinstance(node, ast.ClassDef) and node.name == "RouteSearchView":
                method = next(n for n in node.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "interaction_check")
                nodes.append(method)
        self.ns = {
            "GUILD_ID": 0, "CHANNEL_ID": 0, "CHEMISTRY_CHANNEL_ID": 1552593568357548032,
            "DEFAULT_MODE": "복합", "CHANNEL_MODE": {}, "re": re, "random": random, "discord": discord,
            "CHESS_READY": False, "OMOK_READY": False, "QUORIDOR_READY": False,
            "GAMES": SimpleNamespace(get=Mock(return_value=None), drop=Mock()),
            "lock_now": Mock(return_value=False), "lock_delay": Mock(return_value=0), "DELAYING": set(),
            "asyncio": SimpleNamespace(sleep=AsyncMock()),
            "ROUTE_READY": True, "ROUTE_SEQUENCE_LENGTHS": (4, 6, 8),
            "parse_shield_state": Mock(return_value=("벽", 6)),
            "RouteSearchView": Mock(return_value=SimpleNamespace(embed=Mock(return_value=discord.Embed(title="route")), message=None)),
            "handle_game_word": AsyncMock(), "begin_game": AsyncMock(),
            "game_dictionary": Mock(side_effect=lambda mode: SimpleNamespace(name=mode)),
            "JoinView": Mock(return_value=SimpleNamespace(message=None)), "gm": SimpleNamespace(START_SHIELD=12),
        }
        for name in self.RENDERERS:
            self.ns[name] = Mock(return_value=[discord.Embed(title=name)] if name == "jonggyeol_embeds" else discord.Embed(title=name))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), self.ns)
        self.handle = self.ns["on_message"]

    def message(self, content, channel, guild=1, bot=False):
        return SimpleNamespace(content=content, author=SimpleNamespace(id=10, bot=bot, display_name="player"),
                               guild=SimpleNamespace(id=guild) if guild is not None else None,
                               channel=SimpleNamespace(id=channel, send=AsyncMock(), parent_id=self.STANDARD))

    def clear_lookup_calls(self):
        for name in self.RENDERERS + ("RouteSearchView", "lock_now"):
            self.ns[name].reset_mock()

    async def test_all_lookup_commands_blocked_in_training_arenas_and_other_channels(self):
        channels = [*self.TRAINING, *self.ARENAS, 1548658703014830170, 1548663510417014935,
                    1548690709199069295, 999, 1000]
        commands = [*self.SHARED, "!루트 벽6", "!탐색 벽6", "!중간벽 2", "!공격", "  !한방기  "]
        for channel in channels:
            for command in commands:
                with self.subTest(channel=channel, command=command):
                    self.clear_lookup_calls()
                    msg = self.message(command, channel)
                    await self.handle(msg)
                    msg.channel.send.assert_awaited_once()
                    self.assertIn(str(self.STANDARD), msg.channel.send.await_args.args[0])
                    self.assertNotIn("embed", msg.channel.send.await_args.kwargs)
                    for name in self.RENDERERS + ("RouteSearchView", "lock_now"):
                        self.ns[name].assert_not_called()

    async def test_shared_commands_use_fixed_dictionary_in_correct_channels(self):
        self.ns["CHANNEL_MODE"] = {self.STANDARD: "복합", self.COMPLEX: "표준"}
        for channel, mode in ((self.STANDARD, "표준"), (self.COMPLEX, "복합")):
            for command, renderer in self.SHARED.items():
                with self.subTest(channel=channel, command=command):
                    self.clear_lookup_calls()
                    msg = self.message(command, channel)
                    await self.handle(msg)
                    args = ("기", mode, 1) if renderer == "embed_mid" else ("기", mode)
                    self.ns[renderer].assert_called_once_with(*args)
                    msg.channel.send.assert_awaited_once()

    async def test_standard_routes_blocked_in_complex_channel(self):
        for command in ("!루트 벽6", "!탐색벽6"):
            msg = self.message(command, self.COMPLEX)
            await self.handle(msg)
            self.assertIn("표준사전 전용", msg.channel.send.await_args.args[0])
        self.ns["RouteSearchView"].assert_not_called()
        self.ns["embed_route"].assert_not_called()
        self.ns["lock_now"].assert_not_called()

    async def test_standard_routes_work_in_standard_channel(self):
        await self.handle(self.message("!루트 벽6", self.STANDARD))
        self.ns["embed_route"].assert_called_once_with("벽", 6, None)
        await self.handle(self.message("!탐색 벽6", self.STANDARD))
        self.ns["RouteSearchView"].assert_called_once_with(10, "벽", 6)

    async def test_lookup_channels_take_precedence_over_old_single_channel_setting(self):
        self.ns["CHANNEL_ID"] = next(iter(self.TRAINING))
        for channel, mode in ((self.STANDARD, "표준"), (self.COMPLEX, "복합")):
            self.clear_lookup_calls()
            await self.handle(self.message("!중간 기 2", channel))
            self.ns["embed_mid"].assert_called_once_with("기", mode, 2)
        ignored = self.message("!공격 기", 1234)
        await self.handle(ignored)
        ignored.channel.send.assert_not_awaited()
        game = self.message("!대결", self.STANDARD)
        await self.handle(game)
        game.channel.send.assert_not_awaited()

    async def test_guild_bot_and_dm_filters_cannot_bypass_channel_scope(self):
        self.ns["GUILD_ID"] = 1
        for msg in (self.message("!공격 기", self.STANDARD, guild=2),
                    self.message("!공격 기", self.STANDARD, bot=True),
                    self.message("!공격 기", 42, guild=None)):
            await self.handle(msg)
            msg.channel.send.assert_not_awaited()
        self.ns["embed_analysis"].assert_not_called()

    async def test_training_matches_still_start(self):
        for channel, mode in self.TRAINING.items():
            for command in ("!대결", "!시작"):
                self.ns["begin_game"].reset_mock()
                msg = self.message(command, channel)
                await self.handle(msg)
                self.ns["begin_game"].assert_awaited_once()
                self.assertEqual(self.ns["begin_game"].await_args.args[1].name, mode)

    async def test_arena_matches_still_start(self):
        for channel, mode in self.ARENAS.items():
            self.ns["JoinView"].reset_mock()
            msg = self.message("!경기", channel)
            await self.handle(msg)
            self.ns["JoinView"].assert_called_once()
            self.assertEqual(self.ns["JoinView"].call_args.args[2].name, mode)
            self.assertIn("view", msg.channel.send.await_args.kwargs)

    async def test_word_submission_and_forfeit_still_work(self):
        game = SimpleNamespace(players=[10, None], finish=Mock(), board=Mock(return_value=discord.Embed(title="end")))
        self.ns["GAMES"].get.return_value = game
        msg = self.message("사과", next(iter(self.TRAINING)))
        await self.handle(msg)
        self.ns["handle_game_word"].assert_awaited_once_with(game, msg)
        msg.content = "!기권"
        await self.handle(msg)
        game.finish.assert_called_once()
        self.ns["GAMES"].drop.assert_called_once_with(msg.channel.id)

    async def test_matches_still_blocked_in_lookup_channels(self):
        for channel in (self.STANDARD, self.COMPLEX):
            for command in ("!시작", "!대결", "!경기"):
                msg = self.message(command, channel)
                await self.handle(msg)
                self.assertIn("조회·탐색용", msg.channel.send.await_args.args[0])
        self.ns["begin_game"].assert_not_awaited()
        self.ns["JoinView"].assert_not_called()

    async def test_delay_remains_standard_only(self):
        self.ns["lock_now"].return_value = True
        await self.handle(self.message("!공격 기", self.STANDARD))
        self.ns["asyncio"].sleep.assert_awaited_once_with(0)
        self.assertEqual(self.ns["DELAYING"], set())
        self.ns["asyncio"].sleep.reset_mock()
        await self.handle(self.message("!공격 기", self.COMPLEX))
        self.ns["asyncio"].sleep.assert_not_awaited()

    async def test_route_buttons_require_standard_channel_and_owner(self):
        view = SimpleNamespace(user_id=10)
        for channel, user, expected in ((self.STANDARD, 10, True), (self.COMPLEX, 10, False),
                                         (next(iter(self.TRAINING)), 10, False), (self.STANDARD, 11, False)):
            interaction = SimpleNamespace(channel_id=channel, user=SimpleNamespace(id=user),
                                          response=SimpleNamespace(send_message=AsyncMock()))
            allowed = await self.ns["interaction_check"](view, interaction)
            self.assertEqual(allowed, expected)
            if not expected:
                self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
