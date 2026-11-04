#!/usr/bin/env python3
"""Independent v2 static-leaf and raw-game regression tests."""
from functools import lru_cache
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from verify import VerificationError
from verify_v2 import IndependentModelV2, verify_v2


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def files(self, words, initial="가", history=None):
        dictionary = self.base / "words.txt"
        dictionary.write_text(" ".join(words), encoding="utf-8")
        position = self.base / "position.json"
        position.write_text(json.dumps({"initial_syllable": initial, "history": history or []},
                                       ensure_ascii=False), encoding="utf-8")
        return dictionary, position, IndependentModelV2(dictionary.read_bytes(), 0)

    def certificate(self, model, current, counts):
        nodes = []
        memo = {}

        def emit(current, counts):
            counts, static = model.normalize(current, counts)
            key = (current, counts)
            if key in memo:
                return memo[key]
            moves = []
            if static == -1:
                outcome = False
                for group in model.outgoing[current]:
                    if counts[group]:
                        child_vertex, child_counts, _ = model.child_v2(current, counts, group)
                        child_id, child_result = emit(child_vertex, child_counts)
                        moves.append([group, child_id])
                        if not child_result:
                            outcome = True
                            moves = [moves[-1]]
                            break
            else:
                outcome = bool(static)
            identifier = len(nodes)
            nodes.append({"id": identifier, "v": current, "c": counts.hex(),
                          "r": "W" if outcome else "L", "m": moves})
            memo[key] = identifier, outcome
            return identifier, outcome

        root, result = emit(current, counts)
        lines = [{"format": "route-proof-v2", "vertices": len(model.syllables),
                  "groups": len(model.edges), "root": root}] + nodes
        return lines, result

    def write_proof(self, lines):
        proof = self.base / "proof.jsonl"
        proof.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        return proof

    def test_static_chain_and_loop(self):
        for words, expected in [(["가나", "나다"], "L"), (["가가"], "W"),
                                (["가가", "가나", "나다"], "W")]:
            dictionary, position, model = self.files(words)
            lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
            result = verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)
            self.assertEqual(result["result_for_player_to_move"], expected)
            self.assertEqual(result["checked_static_leaves"], 1)
            self.assertEqual(result["checked_certificate_states"], 1)

    def test_static_verdict_cannot_be_forged(self):
        dictionary, position, model = self.files(["가나", "나다"])
        lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
        lines[-1]["r"] = "W"
        with self.assertRaisesRegex(VerificationError, "static label is false"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_dynamic_cycle_needs_proof(self):
        dictionary, position, model = self.files(["가나", "나다", "다가"])
        lines, expected = self.certificate(model, model.vertex["가"], model.full_counts)
        self.assertTrue(expected)
        result = verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)
        self.assertEqual(result["checked_certificate_states"], 2)
        self.assertEqual(result["checked_static_leaves"], 1)
        lines[-1]["k"] = "static"
        with self.assertRaisesRegex(VerificationError, "false static"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_unknown_loss_cannot_omit_choices(self):
        dictionary, position, model = self.files(["가나", "나다", "다마", "마가"])
        lines, expected = self.certificate(model, model.vertex["가"], model.full_counts)
        self.assertFalse(expected)
        lines[-1]["m"] = []
        with self.assertRaisesRegex(VerificationError, "omits legal move"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_known_winning_exit_is_removed_from_unknown_core(self):
        _, _, model = self.files(["가나", "나다", "다가", "가마", "마바"])
        current = model.vertex["가"]
        counts, static = model.normalize(current, model.full_counts)
        self.assertEqual(static, -1)
        self.assertEqual(sum(counts), 3)
        self.assertEqual(counts[model.group[model.vertex["가"], model.vertex["마"]]], 0)
        self.assertEqual(model.normalize(current, counts), (counts, -1))

    def test_literal_history_reuse_and_illegal_move_rejected(self):
        dictionary, position, model = self.files(["가가", "가나", "나다", "다가"])
        lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
        proof = self.write_proof(lines)
        position.write_text(json.dumps({"initial_syllable": "가", "history": ["가가", "가가"]}))
        with self.assertRaisesRegex(VerificationError, "reused history word"):
            verify_v2(dictionary, position, proof, expected_word_count=0)
        position.write_text(json.dumps({"initial_syllable": "가", "history": ["나다"]}))
        with self.assertRaisesRegex(VerificationError, "illegal history connection"):
            verify_v2(dictionary, position, proof, expected_word_count=0)

    def test_wrong_history_root_rejected(self):
        dictionary, position, model = self.files(["가나", "나다", "다가"])
        lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
        position.write_text(json.dumps({"initial_syllable": "가", "history": ["가나"]}))
        with self.assertRaisesRegex(VerificationError, "root does not match exact requested history"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_wrong_child_state_rejected(self):
        dictionary, position, model = self.files(["가나", "나다", "다가"])
        lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
        self.assertEqual(len(lines), 3)
        # Replace the child by a different valid terminal L state. Its own leaf
        # is true, but the parent move cannot lead to it.
        lines[1]["c"] = bytes(len(model.edges)).hex()
        with self.assertRaisesRegex(VerificationError, "incorrect child state"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_unknown_label_rejected(self):
        dictionary, position, model = self.files(["가가"])
        lines, _ = self.certificate(model, model.vertex["가"], model.full_counts)
        lines[-1]["r"] = "unknown"
        with self.assertRaisesRegex(VerificationError, "unknown result"):
            verify_v2(dictionary, position, self.write_proof(lines), expected_word_count=0)

    def test_full_three_vertex_raw_game_comparison(self):
        words_universe = [a + b for a in "가나다" for b in "가나다"]
        comparisons = 0
        for bits in range(1, 1 << len(words_universe)):
            words = [w for index, w in enumerate(words_universe) if bits & (1 << index)]
            model = IndependentModelV2(" ".join(words).encode(), 0)

            @lru_cache(None)
            def raw(current, available):
                return any(not raw(w[-1], available ^ (1 << index))
                           for index, w in enumerate(words)
                           if available & (1 << index) and w[0] == current)

            @lru_cache(None)
            def reduced(current, counts):
                counts, static = model.normalize(current, counts)
                if static != -1:
                    return bool(static)
                for group in model.outgoing[current]:
                    if counts[group]:
                        child, remainder, _ = model.child_v2(current, counts, group)
                        if not reduced(child, remainder):
                            return True
                return False

            for syllable in model.syllables:
                current = model.vertex[syllable]
                self.assertEqual(raw(syllable, (1 << len(words)) - 1),
                                 reduced(current, model.full_counts), (words, syllable))
                comparisons += 1
        self.assertEqual(comparisons, 1488)

    def test_cpp_v2_certificates(self):
        solver = Path(__file__).parent / "solver_v2"
        if not solver.exists():
            self.skipTest("solver_v2 not compiled yet")
        source = random.Random(28817)
        checked = 0
        for case in range(60):
            letters = "가나다마바"[:source.randrange(2, 6)]
            words = []
            for a in letters:
                for b in letters:
                    for parallel in range(source.choices((0, 1, 2), (7, 3, 1))[0]):
                        words.append(a + "아" * parallel + b)
            words = words[:14] or ["가나"]
            first = source.choice(words)
            cache = self.base / f"cache_{case}.bin"
            for history in ([], [], [first]):
                dictionary, position, model = self.files(words, first[0], history)
                current, counts, used = model.position(json.loads(position.read_text()))
                graph = self.base / "input.txt"
                graph.write_text(f"{len(model.syllables)} {len(model.edges)} {current}\n"
                                 + "".join(f"{a} {b} {c}\n" for (a, b), c in zip(model.edges, counts)))
                proof = self.base / "cpp_proof.jsonl"
                command = [str(solver), str(graph), "--seconds", "5", "--nodes", "100000",
                           "--proof", str(proof), "--cache", str(cache)]
                process = subprocess.run(command, capture_output=True, text=True, check=True)
                result = json.loads(process.stdout)
                checked_result = verify_v2(dictionary, position, proof, graph, 0)

                @lru_cache(None)
                def raw(current_syllable, available):
                    return any(not raw(word[-1], available ^ (1 << index))
                               for index, word in enumerate(words)
                               if available & (1 << index) and word[0] == current_syllable)

                available = sum(1 << index for index, word in enumerate(words) if word not in used)
                expected = raw(model.syllables[current], available)
                self.assertEqual(result["result"], "win" if expected else "loss")
                self.assertEqual(checked_result["result_for_player_to_move"], "W" if expected else "L")
                checked += 1
        self.assertEqual(checked, 180)


if __name__ == "__main__":
    unittest.main(verbosity=2)
