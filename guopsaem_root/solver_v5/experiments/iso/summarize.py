#!/usr/bin/env python3
"""Summary of solver_v5_isolog counters (stderr JSON line) for RESULT_KO.md.

usage: summarize.py NAME=STATS_FILE ...
Buckets of mid_by_groups / children*: index i <= 64 is exactly i live groups; i > 64 covers
64 + 32 * (i - 65) + 1 .. 64 + 32 * (i - 64) live groups.
"""
import json
import sys


def upper(i):
    return i if i <= 64 else 64 + 32 * (i - 64)


def main():
    out = {}
    for arg in sys.argv[1:]:
        name, path = arg.split('=', 1)
        d = json.loads(open(path).read().strip().splitlines()[-1])
        h = d['mid_by_groups']
        tot = sum(h)

        def share(pred):
            return sum(x for i, x in enumerate(h) if pred(i))
        dh = d['mid_by_depth8']
        acc, q = 0, {}
        for i, x in enumerate(dh):
            acc += x
            for p in (50, 90, 99):
                if p not in q and acc * 100 >= p * tot:
                    q[p] = f'<= {i * 8 + 7}'
        small = [i for i in range(len(h)) if upper(i) <= 64]
        ch, st, tp = (sum(d[k]) for k in ('children', 'children_static', 'children_tt_proven'))
        sch, sst, stp = (sum(d[k][i] for i in small) for k in ('children', 'children_static', 'children_tt_proven'))
        out[name] = {
            'mid_calls': tot,
            'min_live_groups': d['min_groups'],
            'max_depth': d['max_depth'],
            'depth_quantiles': q,
            'mid_le_24_groups': share(lambda i: upper(i) <= 24),
            'mid_le_64_groups': share(lambda i: upper(i) <= 64),
            'mid_le_256_groups': share(lambda i: upper(i) <= 256),
            'mid_gt_1024_groups': share(lambda i: upper(i) > 1024),
            'children': ch, 'children_static': st, 'children_tt_proven': tp,
            'children_per_mid': round(ch / tot, 2),
            'small_parents_children': sch, 'small_parents_children_static': sst, 'small_parents_children_tt_proven': stp,
            'mid_ended_by_static_child': sum(d['mid_static_win']),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
