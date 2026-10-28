#!/bin/bash
# batch.sh LISTFILE SECONDS TAG PAR [solver args] : run solver_v3 on tune/<name>.txt for each name (first column)
S=/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/improve/solver
list=$1; sec=$2; tag=$3; par=$4; shift 4
mkdir -p $S/tune/res_$tag
cut -f1 $list | xargs -P $par -I{} sh -c "$S/solver_v3 $S/tune/{}.txt --seconds $sec --tt-mb 1024 $* > $S/tune/res_$tag/{}.json 2>&1"
python3 - $S/tune/res_$tag $list <<'PY'
import json,sys,os,math
d=sys.argv[1]; names=[l.split('\t')[0] for l in open(sys.argv[2]) if l.strip()]
solved=0; tot=0; lg=0
for n in names:
    o=json.load(open(f"{d}/{n}.json"))
    r=o["result"]; solved+= r!="unknown"; tot+=o["mid_calls"]; lg+=math.log(max(1,o["mid_calls"]))
    print(n, r, o["mid_calls"], round(o["seconds"],2), o["pn"], o["dn"])
print("SUMMARY solved",solved,"of",len(names),"total_mid",tot,"geomean_mid",round(math.exp(lg/len(names))))
PY
