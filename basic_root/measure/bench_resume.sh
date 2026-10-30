#!/bin/bash
# bench_resume.sh NAME PROBE_S PROBE_THREADS PROBE_MB FINAL_THREADS FINAL_MB [fresh]
# research pattern: probe (unknown) -> final run. Compares "final from scratch" with "final resumed from the probe's TT".
S=/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad; M=$S/measure; B=$M/solver_v3r; P=$S/gyeok_run/pos
n=$1; ps=$2; pt=$3; pm=$4; ft=$5; fm=$6; mkdir -p $M/bench
o=$M/bench/$n
$B $P/$n.txt --seconds $ps --threads $pt --tt-mb $pm --tt-save $o.tt > $o.probe.json
$B $P/$n.txt --seconds 3000 --threads $ft --tt-mb $fm --tt-load $o.tt > $o.resume.json
ls -la $o.tt | awk '{print $5}' > $o.ttsize
rm -f $o.tt
if [ "$7" = fresh ]; then $B $P/$n.txt --seconds 3000 --threads $ft --tt-mb $fm > $o.fresh.json; fi
echo done $n
