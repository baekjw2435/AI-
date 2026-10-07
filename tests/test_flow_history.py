"""Supported 9–12 move contexts must fall back when playable evidence is thin."""

import unittest

import route_engine as rq


NO_RECENT = {"maxWeight": 0, "minimumContextTotal": float("inf"),
             "confidencePrior": 20, "maxScoreAdjustment": 0}
POLICY = {"maxHistory": 12, "supportedHistory": 8,
          "longHistoryMinimumMatches": 5, "longHistoryMinimumMoves": 5,
          "historyPolicyVersion": "v1.27-history12-supported"}
LETTERS = "가나다라마바사아자차카타파"
HISTORY = [(LETTERS[i:i + 2], 0, LETTERS[i]) for i in range(12)]


def fixture(rows, policy=None, history=None, shield=0, dictionary_words=None):
    """rows: (history length, distinct matches, [(word, count, choice matches)])."""
    history = HISTORY if history is None else history
    words = list(dict.fromkeys([move[0] for move in history] +
                              [word for _length, _matches, choices in rows for word, _n, _m in choices]))
    ids = {word: i for i, word in enumerate(words)}
    contexts = []
    for length, matches, choices in rows:
        suffix = history[len(history) - length:]
        contexts.append(["파", shield, [ids[move[0]] for move in suffix],
                         sum(count for _word, count, _matches in choices), matches,
                         [[ids[word], count, [[0, count]], choice_matches, []]
                          for word, count, choice_matches in choices]])
    flow = rq.FlowPolicy({"words": words, "players": ["자료"],
                          "policy": dict(POLICY if policy is None else policy), "contexts": contexts})
    first_words = {}
    for word in words if dictionary_words is None else dictionary_words:
        first_words.setdefault(word[0], []).append(word)
    core = rq.StandardCore(first_words, {s: len(ws) for s, ws in first_words.items()},
                           set(), set(), {}, None, None, 0, NO_RECENT, flow=flow)
    return flow, core


class SupportedFlowHistoryTests(unittest.TestCase):
    def test_supported_twelve_moves_take_priority_over_shorter_context(self):
        flow, core = fixture([(12, 5, [("파하", 5, 5)]), (8, 20, [("파호", 20, 20)])])
        context = rq.flow_context(flow, "파", 0, HISTORY)
        self.assertEqual(context["historyLength"], 12)
        rows = rq.analyze_candidates(core, core.words_for("파", set()), "파", 0, set(), history=HISTORY)
        first = min(rows, key=rq.sort_key)
        self.assertEqual(first["word"], "파하")
        self.assertEqual(first["flow"]["historyLength"], 12)
        self.assertEqual(first["flowRanking"]["availableCount"], 5)

    def test_missing_longest_context_uses_each_supported_nine_to_eleven_suffix(self):
        for length in (9, 10, 11):
            with self.subTest(length=length):
                flow, _core = fixture([(length, 5, [("파하", 5, 5)]), (8, 2, [("파호", 2, 2)])])
                self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY)["historyLength"], length)

    def test_rare_twelve_move_context_falls_back_to_supported_eleven(self):
        flow, _core = fixture([(12, 4, [("파하", 4, 4)]),
                              (11, 5, [("파호", 5, 5)]), (8, 20, [("파가", 20, 20)])])
        self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY)["historyLength"], 11)

    def test_long_context_requires_both_move_and_match_thresholds(self):
        for moves, matches, override in ((50, 4, {}), (5, 5, {"longHistoryMinimumMoves": 6})):
            with self.subTest(moves=moves, matches=matches, override=override):
                policy = {**POLICY, **override}
                flow, _core = fixture([(12, matches, [("파하", moves, matches)]),
                                      (8, 1, [("파호", 1, 1)])], policy=policy)
                self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY)["historyLength"], 8)

    def test_overlapping_choice_matches_are_not_summed_to_support_long_history(self):
        flow, _core = fixture([(12, 8, [("파하", 4, 4), ("파호", 4, 4)]),
                              (8, 1, [("파가", 1, 1)])])
        self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY)["historyLength"], 8)

    def test_playable_filter_removes_used_support_before_choosing_long_context(self):
        flow, core = fixture([(12, 40, [("파하", 100, 40), ("파호", 1, 1)]),
                              (8, 10, [("파호", 10, 10)])])
        self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY)["historyLength"], 12)
        self.assertEqual(rq.flow_context(flow, "파", 0, HISTORY, lambda word: word != "파하")["historyLength"], 8)
        used = {move[0] for move in HISTORY} | {"파하"}
        rows = rq.analyze_candidates(core, ["파하", "파호"], "파", 0, used, history=HISTORY)
        ranked = sorted(rows, key=rq.sort_key)
        self.assertEqual(ranked[0]["word"], "파호")
        self.assertEqual(ranked[0]["flow"]["historyLength"], 8)
        self.assertFalse(ranked[1]["legal"])

    def test_shield_illegal_long_choices_cannot_prevent_shorter_fallback(self):
        history = [(word, 10 - i, current) for i, (word, _shield, current) in enumerate(HISTORY[-9:])]
        _flow, core = fixture([(9, 40, [("파끝", 100, 40), ("파호", 1, 1)]),
                               (8, 10, [("파호", 10, 10)])], history=history, shield=1,
                              dictionary_words=[move[0] for move in history] + ["파끝", "파호", "호수"])
        used = {move[0] for move in history}
        rows = rq.analyze_candidates(core, ["파끝", "파호"], "파", 1, used, history=history)
        self.assertFalse(rows[0]["legal"])
        self.assertTrue(rows[1]["legal"])
        self.assertEqual(rows[1]["flow"]["historyLength"], 8)
        self.assertEqual(min(rows, key=rq.sort_key)["word"], "파호")

    def test_non_dictionary_observation_cannot_support_long_context(self):
        _flow, core = fixture([(12, 40, [("파없는말", 100, 40), ("파호", 1, 1)]),
                               (8, 10, [("파호", 10, 10)])], dictionary_words=["파호"])
        rows = rq.analyze_candidates(core, ["파호"], "파", 0, set(), history=HISTORY)
        self.assertEqual(rows[0]["flow"]["historyLength"], 8)

    def test_existing_eight_move_behavior_does_not_gain_new_sample_restrictions(self):
        # Old files with maxHistory=12 but no threshold fields also use safe defaults.
        for policy in (POLICY, {"maxHistory": 12}):
            flow, _core = fixture([(12, 4, [("파하", 4, 4)]),
                                  (8, 1, [("파호", 1, 1)])], policy=policy)
            context = rq.flow_context(flow, "파", 0, HISTORY, playable=lambda _word: False)
            self.assertEqual(context["historyLength"], 8)
            self.assertEqual(context["choices"]["파호"]["count"], 1)

    def test_history_older_than_twelve_does_not_affect_context_lookup(self):
        flow, _core = fixture([(12, 5, [("파하", 5, 5)]), (8, 2, [("파호", 2, 2)])])
        expected = rq.flow_context(flow, "파", 0, HISTORY)
        for prefix in ([ ("파옛가", 0, "파") ],
                       [("가이전가", 0, "가"), ("가또이전가", 0, "가")]):
            self.assertEqual(rq.flow_context(flow, "파", 0, prefix + HISTORY), expected)

    def test_older_used_word_still_cannot_be_played_or_counted_as_long_support(self):
        old = "파옛가"
        _flow, core = fixture([(12, 45, [(old, 100, 40), ("파호", 5, 5)]),
                               (8, 2, [("파호", 2, 2)])])
        history = [(old, 0, "파")] + HISTORY
        used = {move[0] for move in history}
        rows = rq.analyze_candidates(core, [old, "파호"], "파", 0, used, history=history)
        self.assertFalse(rows[0]["legal"])
        self.assertEqual(rows[1]["flow"]["historyLength"], 12)
        self.assertEqual(rows[1]["flowRanking"]["availableCount"], 5)
        self.assertEqual(min(rows, key=rq.sort_key)["word"], "파호")

    def test_manual_shield_change_prevents_reusing_a_twelve_move_context(self):
        flow, _core = fixture([(12, 5, [("파하", 5, 5)]), (0, 2, [("파호", 2, 2)])], shield=1)
        context = rq.flow_context(flow, "파", 1, HISTORY)
        self.assertEqual(context["historyLength"], 0)


if __name__ == "__main__":
    unittest.main()
