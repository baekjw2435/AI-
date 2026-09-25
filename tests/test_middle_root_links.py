"""Regression checks for standard-dictionary middle-chain root links."""
import contextlib
import io
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


class MiddleRootLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        previous_directory = os.getcwd()
        try:
            os.chdir(repo)
            with patch.dict(os.environ, {"DISCORD_TOKEN": "offline-test-token"}), \
                    patch("discord.Client.run") as connect, contextlib.redirect_stdout(io.StringIO()):
                cls.app = runpy.run_path(str(repo / "main.py"), run_name="middle_root_tests")
        finally:
            os.chdir(previous_directory)
        connect.assert_called_once_with("offline-test-token")
        cls.live = cls.app["embed_mid"].__globals__
        cls.words = set((repo / "standard_words.txt").read_text(encoding="utf-8").splitlines())

    def test_all_user_examples_are_found_and_highlight_the_penultimate_syllable(self):
        for word in ("간핍히", "음덕가", "낭족산", "결벽성", "반달가슴곰", "격정범죄인", "옥돔과"):
            with self.subTest(word=word):
                found = self.app["mid_root_links"](word[0])
                self.assertIn(word, found)
                pages = self.app["mid_root_pages"](found)
                self.assertIn(f"{word[:-2]}**{word[-2]}**{word[-1]} → {word[-2]}", "\n".join(pages))

    def test_exact_requested_root_list(self):
        expected = set("덕 슴 벽 적 돔 짝 킨 템 냐 럭 칫 죄 죽 업 융 엿 둑 듬 득 섯 율 짚 땀 핍 뱀 볕 냥 런 솥 족 숲 럼 름 늠 률 값".split())
        self.assertEqual(self.app["STD_MID_ROOT_SYLLABLES"], expected)
        self.assertEqual(self.app["STD_MID_ROOT_TARGETS"], expected)

    def test_index_covers_entire_standard_dictionary_not_only_attacks(self):
        targets = self.app["STD_MID_ROOT_TARGETS"]
        expected = {w for w in self.words if len(w) >= 2 and w[-2] in targets
                    and self.app["dec"](w[0]) is not None}
        actual = set().union(*self.app["STD_MID_ROOT_LINKS"].values())
        self.assertEqual(actual, expected)
        attacks = {w for words in self.app["STD_MID_ATTACK"].values() for w in words}
        self.assertIn("결벽성", actual - attacks)

    def test_last_syllable_and_one_letter_words_do_not_match(self):
        for word in ("가슴", "미덕"):
            self.assertTrue(word in self.words, word)
            self.assertNotIn(word, self.app["mid_root_links"](word[0]))
        self.assertNotIn("벽", self.app["mid_root_links"]("벽"))

    def test_standard_dueum_is_forward_only(self):
        dueum = self.app["dueum"]
        self.assertEqual(dueum("률"), "율")
        self.assertEqual(dueum("름"), "늠")
        for syllable in ("율", "늠", "럭", "럼", "런", "냐", "냥"):
            self.assertIsNone(dueum(syllable))
        index = {"름": {"름름틀"}, "늠": {"늠늠틀"}}
        with patch.dict(self.live, {"STD_MID_ROOT_LINKS": index}):
            self.assertEqual(self.app["mid_root_links"]("름"), ["늠늠틀", "름름틀"])
            self.assertEqual(self.app["mid_root_links"]("늠"), ["늠늠틀"])
        self.assertIn("→ 름/늠", "\n".join(self.app["mid_root_pages"](["기름샘"])))

    def test_root_only_results_are_shown_and_do_not_need_attack_file(self):
        with patch.dict(self.live, {"STD_MID_ATTACK": {}}):
            embed = self.app["embed_mid"]("결", "표준")
            self.assertIn("루트음절 연결수", embed.description)
            self.assertIn("결**벽**성", "\n".join(field.value for field in embed.fields))
            self.assertIn("연결수만 표시", embed.fields[-1].value)

    def test_existing_attacks_are_not_removed_when_also_root_links(self):
        with patch.dict(self.live, {"STD_MID_ATTACK": {"간": {"간핍히": 1, "간고름증": 3}}}):
            self.assertEqual(self.app["analyze_mid"]("간", "표준"), (["간핍히"], ["간고름증"], []))
            embed = self.app["embed_mid"]("간", "표준")
            fields = {field.name.split(" · ")[0]: field.value for field in embed.fields}
            self.assertIn("간핍히", fields["⚡ 한방"])
            self.assertIn("간고름증", fields["🗡️ 공격"])
            self.assertIn("간**핍**히", fields["🧭 루트음절 연결수"])

    def test_complex_dictionary_does_not_get_root_links(self):
        self.assertEqual(self.app["mid_root_links"]("결", "복합"), [])
        embed = self.app["embed_mid"]("결", "복합")
        self.assertFalse(any("루트음절 연결수" in field.name for field in embed.fields))

    def test_every_result_is_reachable_without_exceeding_discord_limits(self):
        for syllable in self.app["STD_MID_ROOT_LINKS"]:
            words = self.app["mid_root_links"](syllable)
            pages = self.app["mid_root_pages"](words)
            restored = [line.split(" → ")[0].replace("**", "")
                        for page in pages for line in page.splitlines()]
            self.assertEqual(restored, words)
            for page in range(1, len(pages) + 1):
                embed = self.app["embed_mid"](syllable, "표준", page)
                self.assertLessEqual(len(embed), 6000)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
            if len(pages) > 1:
                self.assertIn(f"!중간 {syllable} 2", self.app["embed_mid"](syllable, "표준").fields[-1].value)
        self.assertLessEqual(len(self.app["HELP_TEXT"]), 2000)

    def test_command_routing_accepts_pages_and_rejects_bad_pages(self):
        import asyncio
        async def check():
            for content, expected in (("!중간 결", "결**벽**성"), ("!중간 적 2", "(2/")):
                msg = SimpleNamespace(content=content, author=SimpleNamespace(bot=False, id=10),
                                      guild=SimpleNamespace(id=1),
                                      channel=SimpleNamespace(id=1544553748565729381, send=AsyncMock()))
                with patch.dict(self.live, {"GUILD_ID": 0, "CHANNEL_ID": 0, "lock_now": lambda: False}):
                    await self.app["on_message"](msg)
                msg.channel.send.assert_awaited_once()
                embed = msg.channel.send.await_args.kwargs["embed"]
                text = "\n".join(field.name + field.value for field in embed.fields)
                self.assertIn(expected, text)
            for argument in ("0", "-1", "가", "2 더", "99999999999999999999"):
                msg.content = "!중간 적 " + argument
                msg.channel.send.reset_mock()
                with patch.dict(self.live, {"GUILD_ID": 0, "CHANNEL_ID": 0, "lock_now": lambda: False}):
                    await self.app["on_message"](msg)
                self.assertIn("페이지는 양의 정수", msg.channel.send.await_args.args[0])
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
