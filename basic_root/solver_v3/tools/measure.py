#!/usr/bin/env python3
"""Run a command, print its stdout last line plus wall time and peak RSS (MB) as JSON."""
import json, resource, subprocess, sys, time
t = time.monotonic()
p = subprocess.run(sys.argv[1:], stdout=subprocess.PIPE, stderr=None, text=True)
w = time.monotonic() - t
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
last = (p.stdout.strip().splitlines() or [""])[-1]
try:
    out = json.loads(last)
except Exception:
    out = {"raw": last}
out["_wall"] = round(w, 2); out["_peak_rss_mb"] = round(ru.ru_maxrss / 1024, 1); out["_rc"] = p.returncode
out["_cpu"] = round(ru.ru_utime + ru.ru_stime, 2)
print(json.dumps(out, ensure_ascii=False))
