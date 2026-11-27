#!/bin/sh
# new way: shared-position planning (exact merges + forced moves), shared proven cache, skip work of decided roots
B=/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/bench42
cd /home/user/AI-
date +%s > $B/new.start
python3 guopsaem_root/tools/frontier.py plan basic_root/words_817.txt 817 $B/roots.txt $B/new > $B/new.plan.log 2>&1
PROVEN_DIR=$B/new/proven TZ=Asia/Seoul python3 -u guopsaem_root/tools/frontier.py solve basic_root/words_817.txt 817 $B/new 120 512 2 > $B/new.log 2>&1
TZ=Asia/Seoul python3 -u guopsaem_root/tools/frontier.py assemble basic_root/words_817.txt 817 $B/new > $B/new.assemble.log 2>&1
date +%s > $B/new.end
