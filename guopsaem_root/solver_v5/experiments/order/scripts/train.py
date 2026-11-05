#!/usr/bin/env python3
"""train.py OUT_WEIGHTS DUMP... : logistic regression (numpy, L2) of the child's result on the
features written by solver_v5_order --dump-features. Each dump file (one root) gets equal total
weight, and the two classes are balanced. Writes bias + 12 weights (raw feature scale) and
prints accuracy / AUC on the training files and, with --test DUMP..., on held-out files."""
import sys, numpy as np
args = sys.argv[1:]
outw = args[0]; rest = args[1:]
test = []
if '--test' in rest:
    i = rest.index('--test'); test = rest[i + 1:]; rest = rest[:i]
def load(files):
    X, y, w = [], [], []
    for f in files:
        a = np.loadtxt(f, usecols=range(10), ndmin=2)
        if len(a) == 0: continue
        lab = a[:, 0]; nm, nw, mx, fo, sd, cc, sh, fl, at = [a[:, j] for j in range(1, 10)]
        fl = fl.astype(int)
        phi = np.stack([np.log1p(nm), np.log1p(nw), np.log1p(mx), fo, np.log1p(sd), cc / 100.0, sh,
                        fl & 1, (fl >> 1) & 1, (fl >> 2) & 1, at, nw.astype(int) & 1], 1)
        ww = np.ones(len(a))
        for c in (0, 1):
            m = lab == c
            if m.sum(): ww[m] = 0.5 / m.sum()
        X.append(phi); y.append(lab); w.append(ww)
    return np.concatenate(X), np.concatenate(y), np.concatenate(w)
def auc(s, y):
    o = np.argsort(s); r = np.empty(len(s)); r[o] = np.arange(1, len(s) + 1)
    p = y == 1; n1 = p.sum(); n0 = len(y) - n1
    return (r[p].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
X, y, w = load(rest)
mu, sd = X.mean(0), X.std(0) + 1e-9
Z = (X - mu) / sd
Z1 = np.hstack([np.ones((len(Z), 1)), Z])
beta = np.zeros(Z1.shape[1]); lam = 1e-3
w = w / w.sum()
for it in range(500):  # Newton
    p = 1 / (1 + np.exp(-Z1 @ beta))
    g = Z1.T @ (w * (p - y)) + lam * np.r_[0, beta[1:]]
    H = (Z1 * (w * p * (1 - p))[:, None]).T @ Z1 + lam * np.diag(np.r_[0, np.ones(len(beta) - 1)])
    step = np.linalg.solve(H, g); beta -= step
    if np.abs(step).max() < 1e-9: break
wr = beta[1:] / sd; b0 = beta[0] - (beta[1:] * mu / sd).sum()
np.savetxt(outw, np.r_[b0, wr][None], fmt='%.8g')
names = 'log1p_nm log1p_nwords log1p_minx forced log1p_sumd core/100 shrink loop sloop lastword att parity'.split()
print('standardized coefficients:', ', '.join(f'{n}={b:+.3f}' for n, b in zip(names, beta[1:])))
s = X @ wr + b0
print(f'train rows={len(y)} acc(balanced)={((s > 0) == (y == 1)) @ w:.3f} auc={auc(s, y):.3f}')
base = np.log1p(X[:, 0])  # mobility alone (default heuristic's signal)
print(f'train auc of mobility nm alone={auc(base, y):.3f}')
if test:
    Xt, yt, wt = load(test); wt /= wt.sum(); st = Xt @ wr + b0
    print(f'test rows={len(yt)} acc(balanced)={((st > 0) == (yt == 1)) @ wt:.3f} auc={auc(st, yt):.3f} auc(nm alone)={auc(np.log1p(Xt[:, 0]), yt):.3f}')
