#!/bin/bash
# sweep.sh IDX SECONDS TAG args... : one run, JSON to logs/sweep_IDX_TAG.json
S=/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad
i=$1; sec=$2; tag=$3; shift 3
python3 $S/improve/solver/tools/measure.py $S/improve/solver/solver_v3 $S/bench/v2_$i.txt --seconds $sec --tt-mb 2048 "$@" > $S/improve/solver/logs/sweep_${i}_${tag}.json 2>&1
