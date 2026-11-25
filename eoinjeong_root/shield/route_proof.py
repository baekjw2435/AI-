#!/usr/bin/env python3
"""보호막 0이 된 루트 음절 자리 중 '쓴 루트 단어가 있는' 자리를 루트전 정식 도구로 확정한다.

자리 = 621단어 루트 사전에서 initial_syllable = x, history = [], initial_used_words = 쓴 루트 단어(정렬).
solver_v5로 증명서(route-proof-v4)를 만들고 verify_v4로 검증한다(guopsaem_root/tools/solve_common의 solve()·verify()).
수락 조건 8개를 모두 통과해야 '확정'. 시간 한도는 정한 값(기본 60초) 한 번만 쓰고 늘리지 않는다.

prove(x, used_route_words, outdir)  → 기록 dict (accepted, result W|L|None, 파일 이름, 해시)
check(record, outdir)               → 검증기에서: 같은 파일을 verify_v4로 다시 검증(수락 조건 8개)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent
BIN = HERE / 'bin'


def _build():
    """solver_v5·verify_v4를 저장소 소스(guopsaem_root)에서 shield/bin/에 컴파일한다(없을 때만)."""
    import subprocess
    BIN.mkdir(exist_ok=True)
    g = REPO / 'guopsaem_root'
    jobs = [(BIN / 'solver_v5', ['g++', '-O3', '-march=x86-64-v3', '-std=c++17', '-o', str(BIN / 'solver_v5'),
                                 str(g / 'solver_v5' / 'solver_v5.cpp'), '-lz', '-pthread']),
            (BIN / 'verify_v4', ['g++', '-O2', '-std=c++17', '-o', str(BIN / 'verify_v4'),
                                 str(g / 'verifier_v4' / 'verify_v4.cpp'), '-lz'])]
    for out, cmd in jobs:
        if not out.exists():
            subprocess.run(cmd, check=True)


_build()
os.environ.setdefault('SOLVER', str(BIN / 'solver_v5'))
os.environ.setdefault('VERIFY_V4', str(BIN / 'verify_v4'))
os.environ.setdefault('VERIFY_LOCK', str(BIN / 'verify.lock'))
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = ROOT / 'words_621.txt'
NWORDS = 621
SECONDS = 60
TT_MB = 512
_model = None


def model():
    global _model
    if _model is None:
        _model = ModelV3(DICT.read_bytes(), NWORDS)
    return _model


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def position_of(x, used_route_words):
    pos = {'initial_syllable': x, 'history': []}
    if used_route_words:
        pos['initial_used_words'] = sorted(used_route_words)
    return pos


def pid_of(x, used_route_words):
    h = hashlib.sha256(json.dumps(position_of(x, used_route_words), ensure_ascii=False).encode()).hexdigest()[:16]
    return f'{x}_{h}'


def prove(x, used_route_words, outdir, seconds=SECONDS, ttmb=TT_MB):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pid = pid_of(x, used_route_words)
    posf, inf, proof = outdir / f'{pid}.pos.json', outdir / f'{pid}.in.txt', outdir / f'{pid}.v4.gz'
    rec_f = outdir / f'{pid}.rec.json'
    if rec_f.exists():
        rec = json.loads(rec_f.read_text(encoding='utf-8'))
        if rec.get('accepted') or rec.get('limit_seconds') == seconds:
            return rec
    m = model()
    posf.write_text(json.dumps(position_of(x, used_route_words), ensure_ascii=False), encoding='utf-8')
    cur, counts, _ = m.position(json.loads(posf.read_text(encoding='utf-8')))
    inf.write_bytes(m.numeric_input(cur, counts))
    sol = sc.solve(inf, proof, seconds, ttmb, tt=outdir / f'{pid}.tt', log=outdir / f'{pid}.log')
    rec = {'id': pid, 'syllable': x, 'used_route_words': sorted(used_route_words), 'limit_seconds': seconds,
           'solver_result': sol.get('result'), 'solver_seconds': sol.get('seconds'), 'accepted': False, 'result': None}
    if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
        want = 'W' if sol['result'] == 'win' else 'L'
        ok, vr = sc.verify(DICT, NWORDS, posf, proof, inf, want, sol.get('proof_nodes', 0))
        rec.update(accepted=ok, result=want if ok else None, acceptance=vr.get('acceptance'),
                   proof_sha256=sha(proof), position_sha256=sha(posf), input_sha256=sha(inf),
                   proof_bytes=proof.stat().st_size)
        sc.release_state(outdir / f'{pid}.tt', ok, proof)
    rec_f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


def check(x, used_route_words, want, outdir):
    """검증기용: 자리 파일이 (x, 쓴 루트 단어)와 정확히 같고, verify_v4가 그 증명서를 want로 수락하는가."""
    outdir = Path(outdir)
    pid = pid_of(x, used_route_words)
    posf, inf, proof = outdir / f'{pid}.pos.json', outdir / f'{pid}.in.txt', outdir / f'{pid}.v4.gz'
    if not (posf.exists() and inf.exists() and proof.exists()):
        return False, '증명서 파일 없음'
    if json.loads(posf.read_text(encoding='utf-8')) != position_of(x, used_route_words):
        return False, '자리 파일이 다름'
    m = model()
    cur, counts, _ = m.position(position_of(x, used_route_words))
    if inf.read_bytes() != m.numeric_input(cur, counts):
        return False, '입력 파일이 다름'
    ok, vr = sc.verify(DICT, NWORDS, posf, proof, inf, want)
    return ok, 'verify_v4 수락' if ok else f"verify_v4 불수락 {vr.get('acceptance')}"
