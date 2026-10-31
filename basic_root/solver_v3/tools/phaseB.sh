#!/bin/bash
S=/home/user/AI-/.work/improve/solver
for i in 3 5 yeokpung; do
  (python3 $S/tools/measure.py $S/solver_v3 $S/pos/in_$i.txt --seconds 600 --tt-mb 2560 --progress 60 --proof $S/proofs/long1t_$i.jsonl.gz > $S/logs/long_v3_1t_$i.json 2> $S/logs/long_v3_1t_$i.err) &
done
wait
echo done > $S/logs/phaseB.done
