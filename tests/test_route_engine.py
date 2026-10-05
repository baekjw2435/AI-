"""Standard explorer v1.25: rule invariants and real-data ranking regressions."""

import json
from pathlib import Path
import unittest

import route_engine as rq


ROOT = Path(__file__).resolve().parents[1]
NO_RECENT = {"maxWeight": 0, "minimumContextTotal": float("inf"),
             "confidencePrior": 20, "maxScoreAdjustment": 0}


def core_for(words, flow=None, learning=None):
    first_words = {}
    for word in words:
        first_words.setdefault(word[0], []).append(word)
    return rq.StandardCore(first_words, {k: len(v) for k, v in first_words.items()},
                           set(), set(), {}, learning, None, 0, NO_RECENT, flow=flow)


def evidence(count, matches, history_length=1):
    return {"count": count, "choiceMatches": matches, "historyLength": history_length}


class FlowRulesTest(unittest.TestCase):
    def test_continuity_checks_syllable_and_shield(self):
        history = [(word, 0, word[0]) for word in
                   ["덕업", "업업", "업시름", "늠률", "율무죽", "죽지뼈"]]
        self.assertEqual(rq.continuous_flow_history(history, "뼈", 0), history)
        self.assertEqual(rq.continuous_flow_history(history, "뼈", 4), [])
        changed = [(word, 5 if i < 3 else shield, current)
                   for i, (word, shield, current) in enumerate(history)]
        self.assertEqual(rq.continuous_flow_history(changed, "뼈", 0), history[-3:])
        self.assertEqual(rq.continuous_flow_history([("사과", 0, "사")] + history[-2:], "뼈", 0), history[-2:])

    def test_standard_dueum_is_forward_and_has_no_extra_rieul_conversion(self):
        for original, expected in {
            "률": ["률", "율"], "름": ["름", "늠"], "녀": ["녀", "여"],
            "럼": ["럼"], "력": ["력", "역"], "족": ["족"], "율": ["율"],
        }.items():
            self.assertEqual(rq.dueum_variants(original), expected)

    def test_duplicate_choices_and_overlapping_games_do_not_inflate_weight(self):
        row = {"word": "족사부착쇄조개", "legal": True, "flow": evidence(100, 2)}
        second = {"word": "족제비업", "legal": True, "flow": evidence(1, 2)}
        context = rq.flow_ranking_context([row, row, second])
        self.assertEqual(context["availableCount"], 101)
        self.assertEqual(context["peakCount"], 100)
        self.assertAlmostEqual(context["weight"], 2 / 12)

    def test_illegal_and_zero_history_observations_do_not_inflate_weight(self):
        rows = [
            {"word": "가가", "legal": False, "flow": evidence(1000, 100)},
            {"word": "가나", "legal": True, "flow": evidence(1000, 100, 0)},
            {"word": "가다", "legal": True, "flow": evidence(3, 3)},
        ]
        context = rq.flow_ranking_context(rows)
        self.assertEqual(context["availableCount"], 3)
        self.assertAlmostEqual(context["weight"], 3 / 23)
        self.assertIsNone(rq.flow_ranking_context(rows[:2]))

    def test_flow_uses_exact_state_and_filters_invalid_start_syllables(self):
        data = rq.FlowPolicy({"words": ["가율", "율가", "율나", "불가"], "players": ["A"],
            "policy": {"maxHistory": 8}, "contexts": [
                ["율", 0, [0], 3, 3, [[1, 1, [[0, 1]], 1, []], [3, 2, [[0, 2]], 2, []]]],
                ["률", 0, [], 7, 7, [[2, 7, [[0, 7]], 7, []]]],
            ]})
        ctx = rq.flow_context(data, "율", 0, [("가율", 0, "가")])
        self.assertEqual(list(ctx["choices"]), ["율가"])
        self.assertIsNone(rq.flow_context(data, "율", 0, []))

    def test_zero_history_context_leaves_baseline_scores_unchanged(self):
        flow = rq.FlowPolicy({"words": ["가나", "가다"], "players": ["A"],
            "policy": {"maxHistory": 8}, "contexts": [
                ["가", 0, [], 100, 100, [[0, 100, [[0, 100]], 100, []]]],
            ]})
        core = core_for(flow.words, flow)
        for row in rq.analyze_candidates(core, flow.words, "가", 0, set()):
            self.assertIsNone(row["flowRanking"])
            self.assertEqual(row["recommendationScore"], row["recentTrend"]["combinedScore"])

    def test_used_and_protected_illegal_candidates_cannot_receive_flow_score(self):
        flow = rq.FlowPolicy({"words": ["나가", "가가", "가끝", "가나"], "players": ["A"],
            "policy": {"maxHistory": 8}, "contexts": [
                ["가", 1, [0], 201, 101, [
                    [1, 100, [[0, 100]], 50, []], [2, 100, [[0, 100]], 50, []],
                    [3, 1, [[0, 1]], 1, []],
                ]],
            ]})
        core = core_for(flow.words + ["나라"], flow)
        rows = rq.analyze_candidates(core, flow.words[1:], "가", 1, {"가가", "나가"},
                                     history=[("나가", 2, "나")])
        ranked = sorted(rows, key=rq.sort_key)
        self.assertEqual(ranked[0]["word"], "가나")
        self.assertEqual(ranked[0]["flowRanking"]["availableCount"], 1)
        for row in rows[:2]:
            self.assertFalse(row["legal"])
            self.assertIsNone(row["flowRanking"])

    def test_follow_count_and_protection_apply_for_every_shield(self):
        core = core_for(["가나", "나라", "나무", "나비"])
        for shield in range(13):
            row = rq.analyze_candidates(core, ["가나"], "가", shield, {"나무"})[0]
            self.assertEqual(row["followCount"], 2)
            self.assertEqual(row["legal"], shield <= 2)
        self.assertTrue(rq.analyze_candidates(core, ["가나"], "가", 12, {"나무"}, False)[0]["legal"])


class RealDataRankingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        words = (ROOT / "standard_words.txt").read_text(encoding="utf-8").splitlines()
        cls.core = core_for([word.strip() for word in words if word.strip()])
        cls.core.learning = rq.load_learning(ROOT / "standard_route_learning.json")
        cls.core.recent = rq.load_learning(ROOT / "standard_route_learning_recent.json")
        cls.core.flow = rq.load_flow(ROOT / "standard_flow_policy.json")
        special = json.loads((ROOT / "standard_special.json").read_text(encoding="utf-8"))
        cls.core.routes = special["routes"]
        cls.core.attacks = set(special["attacks"])
        cls.core.one_shots = set(special["oneShots"])
        recent = json.loads((ROOT / "standard_recent_policy.json").read_text(encoding="utf-8"))
        cls.core.recent_policy = recent["policy"]
        cls.core.recent_days = recent["days"]

    def ranked(self, current, history, used=None, shield=0):
        used = set(used) if used is not None else {move[0] for move in history}
        rows = rq.analyze_candidates(self.core, self.core.words_for(current, used),
                                     current, shield, used, history=history)
        return sorted((row for row in rows if row["legal"]), key=rq.sort_key)

    def test_jok_after_used_jokjijok_preserves_structural_priority(self):
        rows = self.ranked("족", [("족지족", 0, "족"), ("족족", 0, "족")])
        self.assertEqual([(r["word"], r["recommendationScore"]) for r in rows[:3]],
                         [("족제비업", 37.1), ("족사부착쇄조개", 19.0), ("족부권", 14.3)])
        self.assertEqual(rows[0]["flowRanking"]["availableCount"], 3)
        self.assertAlmostEqual(rows[0]["flowRanking"]["weight"], 3 / 23)
        self.assertEqual(rows[0]["flowRanking"]["baselineScore"], 35.2)
        self.assertEqual(rows[1]["flowRanking"]["baselineScore"], 6.9)
        self.assertEqual(rows[0]["flow"]["total"], 85)

    def test_unused_jokjijok_receives_supported_flow_priority(self):
        rows = self.ranked("족", [("족족", 1, "족")])
        self.assertEqual(rows[0]["word"], "족지족")
        self.assertEqual(rows[0]["flow"]["count"], 81)
        self.assertGreater(rows[0]["flowRanking"]["weight"], 0.5)

    def test_six_move_bone_context_preserved(self):
        history = [(word, 0, word[0]) for word in
                   ["덕업", "업업", "업시름", "늠률", "율무죽", "죽지뼈"]]
        rows = self.ranked("뼈", history)
        self.assertEqual(rows[0]["word"], "뼈위축")
        self.assertEqual(rows[0]["flow"]["historyLength"], 6)
        self.assertEqual(rows[0]["flow"]["total"], 256)
        self.assertEqual(rows[0]["flow"]["matchCount"], 240)

    def test_manual_state_edit_breaks_both_flow_and_route_learning_history(self):
        history = [("족지족", 0, "족"), ("족족", 0, "족")]
        rows = self.ranked("족", history, shield=4)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["learning"]["matchedHistoryLength"], 0)
            self.assertIsNone(row["flowRanking"])

    def test_no_available_observed_choices_keeps_baseline(self):
        rows = rq.analyze_candidates(self.core, ["족부권", "족척"], "족", 0,
                                     {"족족", "족지족"}, history=[("족족", 0, "족")])
        for row in rows:
            self.assertIsNone(row["flowRanking"])
            self.assertEqual(row["recommendationScore"], row["recentTrend"]["combinedScore"])

    def test_confirmed_wall_routes_and_middle_dot_normalization(self):
        for shield, expected in {
            5: ["벽바닥", "닥닥", "닥터스톱", "톱스핀", "핀우그리아어족"],
            4: ["벽탑", "탑승객", "객관적도덕", "덕업"],
        }.items():
            route = rq.build_auto_route(self.core, "벽", shield, depth=shield)
            self.assertEqual([word for word, _ in route], expected)
        row = rq.analyze_candidates(self.core, ["핀·우그리아어족"], "핀", 1, set())[0]
        self.assertTrue(row["shieldRoutePick"])


if __name__ == "__main__":
    unittest.main()
