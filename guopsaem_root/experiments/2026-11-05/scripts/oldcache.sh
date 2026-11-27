#!/bin/sh
# old way + shared proven cache only (roots solved directly, one after another, sharing proven positions)
B=/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/bench42
cd /home/user/AI-
date +%s > $B/oldcache.start
PROVEN_DIR=$B/oldcache/proven TZ=Asia/Seoul python3 -u guopsaem_root/tools/run_pass.py basic_root/words_817.txt 817 $B/roots.txt $B/oldcache 120 512 2 > $B/oldcache.log 2>&1
date +%s > $B/oldcache.end
