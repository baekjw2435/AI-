import os, sys, json
from pathlib import Path
SP = Path(sys.argv[1])
os.environ['SOLVER'] = str(SP / 'bin' / 'solver_v5'); os.environ['VERIFY_V4'] = str(SP / 'bin' / 'verify_v4')
os.environ['CHECKPOINT_SECONDS'] = '3'; os.environ['MIN_FREE_GB'] = '0.5'
sys.path.insert(0, str(SP / 'rev' / 'guopsaem_root' / 'tools'))
import solve_common as sc
d = SP / 'work' / 'lossA'; tt = d / 'state.tt'
# A) the root gets solved, but the certificate cannot be written (here: an unwritable proof path)
if tt.exists(): tt.unlink()
sol = sc.solve(SP / 'work' / 'in.txt', d / 'no_such_dir' / 'p.gz', 60, 256, tt=tt, keep_unknown=True, tt_save_max=2000000)
print('A:', {k: sol.get(k) for k in ('result', 'proof_error', 'seconds', 'tt_saves', 'tt_saved')}, '| saved state still on disk:', tt.exists())
# C) low disk: an existing saved state is neither loaded nor kept
tt.write_bytes(b'x' * 100)
sc.free_gb = lambda p: 5.0            # pretend 5.0 GB free; a 2048 MB job wants 2 + MIN_FREE_GB
sc.MIN_FREE_GB = 4.0
cmd, note = sc.solver_cmd('in.txt', 'p.gz', 480, 2048, tt=tt, tt_save_max=2000000)
print('C:', 'note =', repr(note), '| --tt-load in command:', '--tt-load' in cmd, '| --tt-save in command:', '--tt-save' in cmd)
sc.free_gb = lambda p: 3.9
sc.finish_tt(tt, {'result': 'unknown'}, True)
print('C: after an undecided run with 3.9 GB free, saved state still on disk:', tt.exists())
