#!/bin/sh
# keep: undecided states kept after the 40 s stage and resumed in the 80 s stage; nokeep: same without keeping
R=/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/resumekeep
cd /home/user/AI-
for v in keep nokeep; do
  ( if [ $v = keep ]; then K=1; else K=0; fi
    KEEP_UNKNOWN_TT=$K TT_SAVE_MAX=1000000 CHECKPOINT_SECONDS=30 python3 -u guopsaem_root/tools/run_pass.py basic_root/words_817.txt 817 $R/roots.txt $R/$v 40 512 1 > $R/$v.a.log 2>&1
    ls -la $R/$v/tt > $R/$v.tt_after_a.txt 2>&1
    KEEP_UNKNOWN_TT=$K TT_SAVE_MAX=1000000 CHECKPOINT_SECONDS=30 python3 -u guopsaem_root/tools/run_pass.py basic_root/words_817.txt 817 $R/roots.txt $R/$v 80 512 1 > $R/$v.b.log 2>&1
    touch $R/$v.done ) &
done
wait
