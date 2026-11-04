#!/usr/bin/env python3
"""solver_v4 on random small dictionaries: proof must pass verify_v3 and match brute force.
Usage: random_test.py SOLVER WORKDIR [COUNT] [SEED]"""
import json, random, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / 'verifier_v3'))
from verify_v3 import ModelV3, verify_v3  # noqa: E402
from test_v3_bruteforce import random_dictionary, raw_solver  # noqa: E402

solver, work = sys.argv[1], Path(sys.argv[2])
count = int(sys.argv[3]) if len(sys.argv) > 3 else 300
rng = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else 7)
work.mkdir(parents=True, exist_ok=True)
done = shared = 0
for i in range(count):
    words = random_dictionary(rng)
    if rng.random() < 0.5:   # bigger ones too
        words = sorted(set(words) | set(random_dictionary(rng)))
    model = ModelV3(" ".join(words).encode(), 0)
    shared += any(model.shared)
    starts = sorted({w[-1] for w in words} | model.starts)
    initial = rng.choice(starts)
    used = [w for w in words if rng.random() < 0.15]
    pos = {"initial_syllable": initial, "history": [], "initial_used_words": used}
    (work / 'd.txt').write_text(" ".join(words), encoding='utf-8')
    (work / 'p.json').write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
    cur, counts, _ = model.position(pos)
    (work / 'in.txt').write_bytes(model.numeric_input(cur, counts))
    r = subprocess.run([solver, str(work / 'in.txt'), '--seconds', '20', '--tt-mb', '16', '--threads', '1',
                        '--selfcheck', '1', '--proof', str(work / 'pf.jsonl')], capture_output=True, text=True)
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res['result'] in ('win', 'loss'), (res, words, pos)
    v = verify_v3(work / 'd.txt', work / 'p.json', work / 'pf.jsonl', work / 'in.txt', 0)
    index, raw = raw_solver(words)
    expected = raw(initial, sum(1 << index[w] for w in used))
    assert (v['result_for_player_to_move'] == 'W') == expected == (res['result'] == 'win'), (words, pos, v, res)
    done += 1
print({'positions': done, 'with_shared_groups': shared, 'ok': True})
