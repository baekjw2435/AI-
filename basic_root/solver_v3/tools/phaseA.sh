#!/bin/bash
S=/home/user/AI-/.work
for i in 3 5 yeokpung; do
  python3 $S/improve/solver/tools/measure.py $S/verifier/route-verifier-v2/solver_v2 $S/improve/solver/pos/in_$i.txt --seconds 600 --nodes 8000000 > $S/improve/solver/logs/long_v2_$i.json 2>&1
done
echo done > $S/improve/solver/logs/phaseA.done
