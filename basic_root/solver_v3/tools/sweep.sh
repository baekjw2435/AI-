#!/bin/bash
# sweep.sh IDX SECONDS TAG args... : one run, JSON to logs/sweep_IDX_TAG.json
S=/home/user/AI-/.work
i=$1; sec=$2; tag=$3; shift 3
python3 $S/improve/solver/tools/measure.py $S/improve/solver/solver_v3 $S/bench/v2_$i.txt --seconds $sec --tt-mb 2048 "$@" > $S/improve/solver/logs/sweep_${i}_${tag}.json 2>&1
