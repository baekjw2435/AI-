#!/bin/sh
# 1차(600초)가 끝나면, 미확정 루트 국면만 저장 상태에서 이어 1200초 더(합계 30분) 푼다. results/run_config.json roots_pass2.
set -e
cd "$(dirname "$0")/../.."
R=apmal_root/results
B=eoinjeong_root/shield/bin
while [ ! -e $R/roots/DONE_roots_600s ]; do sleep 30; done
mkdir -p $R/roots/res_pass1_600s && cp $R/roots/res/*.json $R/roots/res_pass1_600s/
SOLVER=$PWD/$B/solver_v5 VERIFY_V4=$PWD/$B/verify_v4 VERIFY_LOCK=$PWD/$B/verify.lock TT_SAVE_MAX=4000000 \
  python3 eoinjeong_root/tools/run_positions.py apmal_root/plans/roots.jsonl $R/roots 1200 3072 4 apmal_root/words_534.txt 534 \
  > $R/roots_pass2_run.log 2>&1
