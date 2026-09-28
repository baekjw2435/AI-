"""Ordered-run searches, real dictionaries and Discord-only channel handling."""
from pathlib import Path
import re
from types import SimpleNamespace
import unicodedata
import unittest
from unittest.mock import AsyncMock, patch

import hunmin_bot as bot
from hunmin_engine import COMPLEX, INITIALS, STANDARD, WORD_FILES, HunminDictionary


class RuleTests(unittest.TestCase):
    def test_runs_have_one_ordered_transition(self):
        valid = ["호흡효소", "허허실실", "하수시설", "하수"]
        invalid = ["항산화성효소", "회사회사", "사회", "호흡", "수소", "하"]
        index = HunminDictionary(valid + invalid + ["하수", "하수A", "하-수", "하 수"])
        self.assertEqual(index.search("ㅎㅅ"), tuple(sorted(valid, key=lambda word: (-len(word), word))))
        self.assertNotIn("하수", index.search("ㅅㅎ"))
        self.assertEqual(index.search("ㅅㅎ"), ("사회",))

    def test_repeated_initials_require_two_syllables(self):
        index = HunminDictionary(["아이", "우아우아", "아", "아가", "자전", "지지자자", "자", "가까"])
        self.assertEqual(index.search("ㅇㅇ"), ("우아우아", "아이"))
        self.assertEqual(index.search("ㅈㅈ"), ("지지자자", "자전"))
        self.assertEqual(index.search("ㄱㄱ"), ())
        self.assertEqual(index.search("ㄱㄲ"), ("가까",))

    def test_normalization_deduplicates_and_preserves_words(self):
        index = HunminDictionary([" 하수 ", "\ufeff하수", unicodedata.normalize("NFD", "하수"), ""])
        self.assertEqual(index.search("ᄒᄉ"), ("하수",))
        self.assertEqual(index.word_count, 1)

    def test_request_validation_and_explicit_page(self):
        self.assertEqual(bot.parse_request(" !ㅎㅅ "), ("ㅎㅅ", 1))
        self.assertEqual(bot.parse_request("!ㅇㅇ 2"), ("ㅇㅇ", 2))
        self.assertEqual(bot.parse_request("!ᄌᄌ 3"), ("ㅈㅈ", 3))
        for content in ("", "!", "!ㅎ", "!ㅎㅅㅅ", "!ㅎ ㅅ", "!하수", "!ㄳㅅ", "!aa",
                        "ㅎㅅ", "!ㅎㅅ 0", "!ㅎㅅ -1", "!ㅎㅅ 1.5", "!ㅎㅅ 2 extra"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                bot.parse_request(content)

    def test_large_lists_paginate_without_loss_and_fit_discord(self):
        words = ["하" * count + "수" for count in range(2, 180)]
        result = bot.build_result(HunminDictionary(words), COMPLEX, "ㅎㅅ")
        self.assertGreater(result.page_count, 1)
        actual = []
        for page in range(result.page_count):
            embed = result.embed(page)
            self.assertLessEqual(len(embed.description), 4096)
            self.assertLessEqual(len(embed), 6000)
            lines = result.pages[page].splitlines()
            self.assertLessEqual(len(lines), bot.PAGE_SIZE)
            actual.extend(lines)
        self.assertEqual(actual, [f"{word}{len(word)}" for word in sorted(words, key=lambda w: (-len(w), w))])

    def test_no_results_and_out_of_range_page(self):
        result = bot.build_result(HunminDictionary([]), STANDARD, "ㅎㅅ")
        self.assertEqual(result.page_count, 1)
        self.assertIn("해당하는 단어가 없습니다", result.embed().description)
        for page in (-1, 1):
            with self.assertRaises(ValueError):
                result.embed(page)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.dictionaries = {mode: HunminDictionary.from_file(cls.root / filename)
                            for mode, filename in WORD_FILES.items()}

    def test_user_example_matches_exact_order(self):
        expected = ["현수선상수", "혼합형학습", "확산성수소", "황화수소수", "횡혈식석실",
                    "하상상승", "하수시설", "하향회선", "하허상실", "한산수수", "한삼수수",
                    "함산소산", "합생수술", "합성사상"]
        self.assertEqual(self.dictionaries[COMPLEX].search("ㅎㅅ")[:14], tuple(expected))
        result = bot.build_result(self.dictionaries[COMPLEX], COMPLEX, "ㅎㅅ")
        self.assertEqual(result.pages[0].splitlines()[:14], [f"{w}{len(w)}" for w in expected])

    def test_dictionary_sources_stay_separate(self):
        standard = self.dictionaries[STANDARD]
        complex_ = self.dictionaries[COMPLEX]
        self.assertEqual(standard.source_rows, 291652)
        self.assertEqual(complex_.source_rows, 868546)
        self.assertNotIn("현수선상수", standard.search("ㅎㅅ"))
        self.assertIn("현수선상수", complex_.search("ㅎㅅ"))
        self.assertEqual(standard.search("ㅎㅅ")[:2], ("황화수소수", "횡혈식석실"))

    def test_real_results_agree_with_independent_hangul_range_regex(self):
        # Check completeness against the full source, not an already truncated list.
        for mode, filename in WORD_FILES.items():
            words = (self.root / filename).read_text(encoding="utf-8-sig").splitlines()
            for pair in ("ㅎㅅ", "ㅅㅎ", "ㅇㅇ", "ㅈㅈ"):
                ranges = []
                for initial in pair:
                    start = 0xAC00 + INITIALS.index(initial) * 588
                    ranges.append(f"[{chr(start)}-{chr(start + 587)}]+")
                regex = re.compile("".join(ranges))
                expected = tuple(sorted({word for word in words if regex.fullmatch(word)}, key=lambda w: (-len(w), w)))
                with self.subTest(mode=mode, pair=pair):
                    self.assertEqual(self.dictionaries[mode].search(pair), expected)
                    result = bot.build_result(self.dictionaries[mode], mode, pair)
                    self.assertEqual("\n".join(result.pages).splitlines(), [f"{w}{len(w)}" for w in expected])
                    self.assertTrue(all(len(result.embed(page).description) <= 4096 for page in range(result.page_count)))


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    def message(self, content, channel=1553954129712254976, *, bot_author=False, guild=True):
        return SimpleNamespace(content=content, author=SimpleNamespace(id=10, bot=bot_author),
                               guild=SimpleNamespace(id=1) if guild else None,
                               channel=SimpleNamespace(id=channel, send=AsyncMock()))

    async def test_fixed_channel_dictionary_and_no_other_channels(self):
        dictionaries = {STANDARD: HunminDictionary(["하수"]), COMPLEX: HunminDictionary(["허허실실"])}
        with patch.dict(bot.DICTIONARIES, dictionaries, clear=True):
            for channel, mode in bot.CHANNEL_MODES.items():
                message = self.message("!ㅎㅅ", channel)
                self.assertTrue(await bot.handle_message(message))
                embed = message.channel.send.await_args.kwargs["embed"]
                self.assertIn(mode, embed.title)
                self.assertIn("하수2" if mode == STANDARD else "허허실실4", embed.description)
            for message in (self.message("!ㅎㅅ", 1544553748565729381), self.message("!ㅎㅅ", 1544722279349485578),
                            self.message("!ㅎㅅ", guild=False), self.message("!ㅎㅅ", bot_author=True), self.message("대화")):
                self.assertFalse(await bot.handle_message(message))
                message.channel.send.assert_not_awaited()

    async def test_help_missing_dictionary_and_bad_page(self):
        with patch.dict(bot.DICTIONARIES, {}, clear=True):
            help_message = self.message("!훈민")
            await bot.handle_message(help_message)
            self.assertIn("ㅎㅎㅅㅅ", help_message.channel.send.await_args.kwargs["embed"].description)
            missing = self.message("!ㅎㅅ")
            await bot.handle_message(missing)
            self.assertIn("불러오지 못했습니다", missing.channel.send.await_args.args[0])
        with patch.dict(bot.DICTIONARIES, {COMPLEX: HunminDictionary(["하수"])}, clear=True):
            message = self.message("!ㅎㅅ 2")
            await bot.handle_message(message)
            self.assertIn("1~1", message.channel.send.await_args.args[0])

    async def test_pagination_owner_channel_bounds_and_timeout(self):
        dictionary = HunminDictionary(["하" * count + "수" for count in range(1, 70)])
        with patch.dict(bot.DICTIONARIES, {COMPLEX: dictionary}, clear=True):
            message = self.message("!ㅎㅅ 2")
            await bot.handle_message(message)
        view = message.channel.send.await_args.kwargs["view"]
        self.assertEqual(view.page, 1)
        interaction = SimpleNamespace(channel_id=message.channel.id, user=SimpleNamespace(id=10),
                                      response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))
        self.assertTrue(await view.interaction_check(interaction))
        interaction.user.id = 11
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])
        interaction.user.id, interaction.channel_id = 10, 1234
        self.assertFalse(await view.interaction_check(interaction))
        interaction.channel_id = message.channel.id
        await view.move(interaction, -1)
        self.assertEqual(view.page, 0)
        self.assertTrue(view.previous.disabled)
        await view.move(interaction, 999)
        self.assertEqual(view.page, view.result.page_count - 1)
        self.assertTrue(view.next_page.disabled)
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(all(button.disabled for button in view.children))
        view.message.edit.assert_awaited_once_with(view=view)


if __name__ == "__main__":
    unittest.main()
