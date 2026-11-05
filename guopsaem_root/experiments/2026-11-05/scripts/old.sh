#!/bin/sh
# old way: solve every root directly (no merging of shared positions, no shared cache)
B=/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/bench42
cd /home/user/AI-
date +%s > $B/old.start
TZ=Asia/Seoul python3 -u guopsaem_root/tools/run_pass.py basic_root/words_817.txt 817 $B/roots.txt $B/old 120 512 2 > $B/old.log 2>&1
date +%s > $B/old.end
