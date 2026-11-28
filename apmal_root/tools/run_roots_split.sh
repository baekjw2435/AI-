#!/bin/sh
# 2차(합계 30분)가 끝나면, 그래도 미확정인 루트를 첫 수별로 나눠 4코어에서 묶음마다 6시간. results/run_config.json roots_split.
# 다시 실행해도 됨(plan.json과 국면별 결과로 이어서 함).
set -e
cd "$(dirname "$0")/../.."
R=apmal_root/results
B=eoinjeong_root/shield/bin
SOLVER=$PWD/$B/solver_v5 VERIFY_V4=$PWD/$B/verify_v4 VERIFY_LOCK=$PWD/$B/verify.lock TT_SAVE_MAX=4000000 \
  python3 apmal_root/tools/split_roots.py $R/roots_split --parts 4 --hours 6 --tt-mb 3072 --jobs 4 \
  --wait-for $R/roots/DONE_roots_1200s >> $R/roots_split_run.log 2>&1
