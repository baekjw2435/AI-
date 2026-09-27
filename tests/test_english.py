"""English connection rules, actual dictionary regressions and Discord output."""
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import english_bot as bot
from english_engine import CLASSIC, KKUTU, EnglishDictionary, normalize_word


class ConnectionTests(unittest.TestCase):
    def test_two_letter_word_never_falls_back_to_one_letter(self):
        index = EnglishDictionary(["ab", "aba", "abacus", "banana", "bacon"])
        self.assertEqual(index.replies("ab"), ("ab", "aba", "abacus"))
        self.assertEqual(index.reply_count("ab"), 3)

    def test_three_letter_word_has_two_alternatives_including_short_replies(self):
        index = EnglishDictionary(["cab", "cabin", "ab", "abacus", "banana"])
        self.assertEqual(index.replies("cab"), ("ab", "abacus", "cab", "cabin"))
        self.assertEqual(index.reply_count("cab"), 4)

    def test_overlap_is_deduplicated(self):
        index = EnglishDictionary(["aa", "aaa", "aaaa", "aab", "cab"])
        self.assertEqual(index.reply_count("aaa"), 4)
        self.assertEqual(index.replies("aaa"), ("aa", "aaa", "aaaa", "aab"))

    def test_classic_uses_only_last_letter(self):
        index = EnglishDictionary(["apple", "elephant", "eel", "lemon"])
        self.assertEqual(index.replies("apple", CLASSIC), ("eel", "elephant"))

    def test_attacks_zero_one_five_six_and_independent_loop(self):
        index = EnglishDictionary(["abzz", "abcd", "abef", "abgh", "abjab", "cdx",
                                   "efa", "efb", "efc", "efd", "efe",
                                   "gha", "ghb", "ghc", "ghd", "ghe", "ghf"])
        result = index.attacks("ab")
        self.assertEqual(result.kills, ("abzz",))
        self.assertIn("abcd", result.attacks)
        self.assertIn("abef", result.attacks)
        self.assertNotIn("abgh", result.attacks)
        self.assertEqual(index.reply_count("abef"), 5)
        self.assertEqual(index.reply_count("abgh"), 6)
        self.assertIn("abjab", result.attacks)
        self.assertEqual(result.loops, ("abjab",))

    def test_queries_are_exact_prefixes_and_loops_return_that_prefix(self):
        index = EnglishDictionary(["abcabc", "abcab", "abjab", "bcabc"])
        self.assertEqual(index.starting("ABC"), ("abcab", "abcabc"))
        self.assertEqual(index.loops("abc"), ("abcabc",))
        self.assertEqual(index.loops("ab"), ("abcab", "abjab"))

    def test_normalization_keeps_whole_words(self):
        self.assertEqual(normalize_word("ATTACHÉ"), "attache")
        self.assertEqual(normalize_word("smørrebrød"), "smorrebrod")
        self.assertEqual(normalize_word("whosev.er"), "whosever")
        self.assertEqual(normalize_word("a"), "")
        self.assertEqual(normalize_word("word definition"), "")
        self.assertEqual(normalize_word("<script>"), "")
        self.assertEqual(EnglishDictionary(["attaché", "attache"]).words, ("attache",))


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = EnglishDictionary.from_file()

    def test_snapshot_contains_short_words_without_dictionary_fragments(self):
        self.assertEqual(len(self.index.words), 99152)
        self.assertEqual(sum(len(w) == 2 for w in self.index.words), 152)
        self.assertIn("ft", self.index.words)
        self.assertIn("smorrebrod", self.index.words)
        self.assertNotIn("rrebr", self.index.words)

    def test_crawl_and_short_word_regressions(self):
        self.assertEqual(self.index.replies("crawl"), ("awl",))
        self.assertEqual(self.index.replies("awl"), ("awl",))
        self.assertEqual(self.index.replies("gift"), ("ft",))
        self.assertEqual(self.index.reply_count("jazz"), 0)
        self.assertEqual(self.index.reply_count("quiz"), 4)

    def test_counts_agree_with_direct_prefix_matching(self):
        for word in ("aa", "ab", "aaa", "cab", "crawl", "jazz", "gift", "quiz", "blue", "yacht"):
            expected = {w for w in self.index.words
                        if w.startswith(word[-2:]) or (len(word) >= 3 and w.startswith(word[-3:]))}
            self.assertEqual(set(self.index.replies(word)), expected, word)
            self.assertEqual(self.index.reply_count(word), len(expected), word)

    def test_classic_loop_examples_and_longest_sort(self):
        loops = self.index.loops("n")
        for word in ("nation", "naturalization", "narration"):
            self.assertIn(word, loops)
        self.assertTrue(all(w.startswith("n") and w.endswith("n") for w in loops))
        result = bot.build_result(self.index, KKUTU, "!장문", "ad", 50)
        words = re.findall(r"`([a-z]+)`", "\n".join(result.body))
        expected = sorted(self.index.starting("ad"), key=lambda w: (-len(w), w))[:50]
        self.assertEqual(words, expected)
        self.assertIn("TOP 50", result.title)

    def test_suffix_results_and_all_pages_fit_discord(self):
        requests = [(KKUTU, "!공격", "ab", 1), (KKUTU, "!공격", "aa", 1),
                    (KKUTU, "!공격", "co", 1), (KKUTU, "!종결", "ght", 1),
                    (KKUTU, "!장문종결", "ght", 100), (CLASSIC, "!종결", "n", 1),
                    (CLASSIC, "!돌림", "n", 1), (CLASSIC, "!장문", "n", 100)]
        for mode, command, query, number in requests:
            result = bot.build_result(self.index, mode, command, query, number)
            for page in range(result.page_count):
                embed = result.embed(page)
                self.assertLessEqual(len(embed), 6000)
                self.assertLessEqual(len(embed.description), 4096)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
            if command == "!종결":
                actual = re.findall(r"`([a-z]+)`", "\n".join(result.body))
                expected = sorted((w for w in self.index.words if w.endswith(query)), key=lambda w: (len(w), w))
                self.assertEqual(actual, expected)

    def test_attack_groups_paginate_without_missing_or_duplicate_entries(self):
        actual = self.index.attacks("ab")
        result = bot.build_result(self.index, KKUTU, "!공격", "ab", 1)
        for name, words in (("한방", actual.kills), ("공격", actual.attacks), ("돌림", actual.loops)):
            shown = []
            for label, pages in result.groups:
                if name in label:
                    shown.extend(re.findall(r"`([a-z]+)`", "\n".join(pages)))
            self.assertEqual(shown, list(words))

    def test_queries_and_options_are_validated(self):
        self.assertEqual(bot.parse_request("!장문 AbC 50", KKUTU), ("!장문", "abc", 50))
        self.assertEqual(bot.parse_request("!종결 ght 2", KKUTU), ("!종결", "ght", 2))
        for content, mode in (("!공격", KKUTU), ("!공격 a", KKUTU), ("!장문 abc", CLASSIC),
                              ("!공격 ab", CLASSIC), ("!장문 n 0", CLASSIC),
                              ("!장문 n 101", CLASSIC), ("!종결 x -1", KKUTU),
                              ("!돌림 n extra", CLASSIC), ("!종결 @everyone", CLASSIC)):
            with self.subTest(content=content), self.assertRaises(ValueError):
                bot.parse_request(content, mode)


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.index = EnglishDictionary(["nation", "naturalization", "narration", "adage",
                                        "adjudication", "abb", "ab", "abuzz", "abjab", "cab"])
        self.patch = patch.object(bot, "DICTIONARY", self.index)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def message(self, content, channel=1553662388752883792):
        return SimpleNamespace(content=content, author=SimpleNamespace(bot=False, id=10),
                               guild=SimpleNamespace(id=1),
                               channel=SimpleNamespace(id=channel, send=AsyncMock()))

    async def test_commands_emit_embeds_only_in_english_channels(self):
        for content in ("!장문 ad", "!공격 ab", "!종결 on", "!장문종결 on", "!도움"):
            msg = self.message(content)
            self.assertTrue(await bot.handle_message(msg))
            self.assertIn("embed", msg.channel.send.await_args.kwargs)
        for channel in (1553662302371319891,):
            for content in ("!장문 n", "!돌림 n", "!종결 n", "!장문종결 n"):
                msg = self.message(content, channel)
                await bot.handle_message(msg)
                self.assertIn("embed", msg.channel.send.await_args.kwargs)
        msg = self.message("!공격 ab", 1544553748565729381)
        self.assertFalse(await bot.handle_message(msg))
        msg.channel.send.assert_not_awaited()

    async def test_invalid_page_or_input_sends_actionable_message(self):
        for content in ("!종결 on 999", "!공격 x", "!장문", "!장문 ad 101"):
            msg = self.message(content)
            await bot.handle_message(msg)
            self.assertTrue(msg.channel.send.await_args.args)
            self.assertNotIn("embed", msg.channel.send.await_args.kwargs)

    async def test_bots_dms_and_plain_chat_are_ignored(self):
        for kind in ("bot", "dm", "chat"):
            msg = self.message("!장문 ad")
            if kind == "bot": msg.author.bot = True
            if kind == "dm": msg.guild = None
            if kind == "chat": msg.content = "apple"
            self.assertFalse(await bot.handle_message(msg))
            msg.channel.send.assert_not_awaited()

    async def test_buttons_enforce_owner_and_channel_then_move(self):
        result = bot.SearchResult(KKUTU, "test", "summary", body=("one", "two"))
        view = bot.SearchView(result, 10, 1553662388752883792)
        self.addCleanup(view.stop)
        for uid, channel, allowed in ((10, view.channel_id, True), (11, view.channel_id, False), (10, 1, False)):
            interaction = SimpleNamespace(channel_id=channel, user=SimpleNamespace(id=uid),
                                          response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))
            self.assertEqual(await view.interaction_check(interaction), allowed)
        self.assertTrue(view.previous.disabled)
        await view.move(interaction, 1)
        self.assertEqual(view.page, 1)
        self.assertTrue(view.next_page.disabled)
        self.assertIn("two", interaction.response.edit_message.await_args.kwargs["embed"].description)
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(all(button.disabled for button in view.children))
        view.message.edit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
