#!/usr/bin/env python3
"""Two builds of the C++ verifier must say exactly the same thing about every certificate.

usage: diff_old_new.py OLD_VERIFY NEW_VERIFY SOLVER WORKDIR [--real DIR ...] [--random COUNT SEED] [--jobs 3]
                       [--extra-below BYTES]

For a change of the verifier that must not change what is accepted (2026-11-12: compressor settings of the
state store). "The same" means: same exit code and the same JSON output, field by field, except
elapsed_seconds. That includes the error text of a rejection.
  --real DIR       every case below DIR that has pos.json, in.txt and a certificate (verify.json or prep.json
                   names it: results/<experiment>/archive and .../sources of the 817-word study). Also run with
                   --digest-only, and once with the WRONG position of a neighbouring case (must be rejected alike);
                   with --extra-below BYTES those two extra runs are made only for certificate files smaller
                   than BYTES (the exact run is made for every case).
  --random N SEED  N random small dictionaries (many shared groups): a certificate from SOLVER for a random
                   position, then mutated certificates (results flipped, moves dropped or redirected, digits and
                   bytes changed, truncations). Every file goes through both builds, exact and --digest-only.
Exit code 0 only if no difference was found.
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError  # noqa: E402

SPECIAL = list('락낙려녀여룽눙리니이라나료뇨요랴야')
PLAIN = list('가다마바사자')
FILL = list('거너더러머버서어저처커터퍼허')


def run(binary, dic, n, pos, proof, inp, digest=False):
    cmd = [binary, '--dictionary', str(dic), '--expected-word-count', str(n), '--position', str(pos), '--proof', str(proof)]
    if inp is not None:
        cmd += ['--input', str(inp)]
    if digest:
        cmd.append('--digest-only')
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        j.pop('elapsed_seconds', None)
    except ValueError:
        j = {'unparsable': r.stdout[-300:]}
    return r.returncode, j


def same(old, new, *args, **kw):
    a, b = run(old, *args, **kw), run(new, *args, **kw)
    return a == b, a, b


def random_dict(rng):
    syl = rng.sample(SPECIAL, rng.randint(3, 6)) + rng.sample(PLAIN, rng.randint(0, 1))
    words = set()
    for _ in range(200):
        if len(words) >= rng.randint(9, 18):
            break
        a, b = rng.choice(syl), rng.choice(syl)
        if rng.random() < 0.15:
            b = a
        words.add(a + b if a != b and rng.random() < 0.2 else a + rng.choice(FILL) + b)
    return sorted(words), syl


def mutate(rng, lines):
    L = [bytearray(x) for x in lines]
    kind = rng.randrange(9)
    i = rng.randrange(1, len(L)) if len(L) > 1 else 0
    if kind == 0:
        L[i] = bytearray(L[i].replace(b'"W"', b'"L"') if b'"W"' in L[i] else L[i].replace(b'"L"', b'"W"'))
    elif kind == 1:
        pos = [p for p, ch in enumerate(L[i]) if 48 <= ch <= 57]
        if pos:
            L[i][rng.choice(pos)] = 48 + rng.randrange(10)
    elif kind in (2, 3, 4, 5):
        node = json.loads(L[i])
        if kind == 2 and node.get('m'):
            node['m'].pop(rng.randrange(len(node['m'])))
        elif kind == 3 and node.get('m') and node['id'] > 0:
            node['m'][rng.randrange(len(node['m']))][1] = rng.randrange(node['id'])
        elif kind == 4 and node.get('m'):
            node['m'][rng.randrange(len(node['m']))][0] = rng.randrange(json.loads(L[0])['groups'])
        elif kind == 5:
            node['m'], node['r'] = [], rng.choice('WL')
        L[i] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 6:
        node = json.loads(L[-1])
        node['r'] = 'W' if node['r'] == 'L' else 'L'
        if node['m'] and rng.random() < 0.5:
            node['m'] = [rng.choice(node['m'])]
        L[-1] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 7 and len(L) > 2:
        cut = rng.randrange(2, len(L))
        L = L[:cut]
        hdr = json.loads(L[0])
        hdr['root'] = cut - 2
        L[0] = bytearray(json.dumps(hdr, separators=(',', ':')).encode())
    else:
        L[i][rng.randrange(len(L[i]))] = rng.randrange(32, 127)
    return [bytes(x) for x in L]


def main():
    old, new, solver, work = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
    rest = sys.argv[5:]
    real, count, seed, jobs, extra_below = [], 0, 1, 3, 1 << 62
    while rest:
        if rest[0] == '--real':
            rest.pop(0)
            while rest and not rest[0].startswith('--'):
                real.append(Path(rest.pop(0)))
        elif rest[0] == '--random':
            count, seed = int(rest[1]), int(rest[2])
            rest = rest[3:]
        elif rest[0] == '--jobs':
            jobs = int(rest[1])
            rest = rest[2:]
        elif rest[0] == '--extra-below':
            extra_below = int(rest[1])
            rest = rest[2:]
        else:
            sys.exit(__doc__)
    work.mkdir(parents=True, exist_ok=True)
    st = {'real_cases': 0, 'real_runs': 0, 'random_dicts': 0, 'random_runs': 0, 'accepted_by_both': 0, 'rejected_by_both': 0, 'different': 0}
    diffs = []

    def note(ok, a, b, what):
        st['accepted_by_both' if a[0] == 0 and b[0] == 0 else 'rejected_by_both'] += ok
        if not ok:
            st['different'] += 1
            diffs.append((what, a, b))

    # ---- real certificates
    dic817 = ROOT.parent / 'basic_root' / 'words_817.txt'
    cases = []
    for base in real:
        for d in sorted(p for p in base.iterdir() if p.is_dir() and (p / 'pos.json').exists() and (p / 'in.txt').exists()):
            if (d / 'proof.v4.gz').exists():
                cases.append((d, d / 'proof.v4.gz'))
            elif (d / 'verify.json').exists():
                h = json.loads((d / 'verify.json').read_text(encoding='utf-8'))['proof_sha256']
                cases.append((d, base / 'certs' / f'{h}.v4.gz'))

    def real_one(k):
        d, proof = cases[k]
        other = cases[(k + 1) % len(cases)][0]
        out = [(same(old, new, dic817, 817, d / 'pos.json', proof, d / 'in.txt'), f'{d} exact')]
        if proof.stat().st_size >= extra_below:
            return out
        out.append((same(old, new, dic817, 817, d / 'pos.json', proof, d / 'in.txt', digest=True), f'{d} digest'))
        if json.loads((other / 'pos.json').read_text(encoding='utf-8')) != json.loads((d / 'pos.json').read_text(encoding='utf-8')):
            out.append((same(old, new, dic817, 817, other / 'pos.json', proof, other / 'in.txt'), f'{d} with the position of {other.name}'))
        return out

    with ThreadPoolExecutor(jobs) as ex:
        for out in ex.map(real_one, range(len(cases))):
            st['real_cases'] += 1
            for (ok, a, b), what in out:
                st['real_runs'] += 1
                note(ok, a, b, what)
    # ---- random certificates and mutations
    rng = random.Random(seed)
    for di in range(count):
        words, syl = random_dict(rng)
        dic = work / 'dict.txt'
        dic.write_text('\n'.join(words) + '\n', encoding='utf-8')
        m = ModelV3(dic.read_bytes(), len(words))
        s = rng.choice(syl)
        pos = {'initial_syllable': s, 'history': []}
        if rng.random() < 0.4:
            rest_words = rng.sample(words, min(len(words), rng.randint(1, 2)))
            pos['initial_used_words'] = rest_words
        try:
            c, k, _ = m.position(pos)
        except VerificationError:
            continue
        (work / 'pos.json').write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
        (work / 'in.txt').write_bytes(m.numeric_input(c, k))
        proof = work / 'p.gz'
        if proof.exists():
            proof.unlink()
        subprocess.run([solver, str(work / 'in.txt'), '--seconds', '20', '--tt-mb', '1', '--proof', str(proof), '--proof-format', 'v4'],
                       capture_output=True, text=True)
        if not proof.exists():
            continue
        st['random_dicts'] += 1
        lines = gzip.open(proof, 'rb').read().split(b'\n')
        if lines and lines[-1] == b'':
            lines.pop()
        variants = [lines]
        for _ in range(8 if len(lines) > 3 else 2):
            v = lines
            for _k in range(rng.randint(1, 3)):
                try:
                    v = mutate(rng, v)
                except (ValueError, KeyError, TypeError, IndexError):
                    pass
            variants.append(v)
        for vi, v in enumerate(variants):
            f = work / 'v.gz'
            with gzip.open(f, 'wb') as g:
                g.write(b'\n'.join(v) + b'\n')
            for digest in (False, True):
                ok, a, b = same(old, new, dic, len(words), work / 'pos.json', f, work / 'in.txt', digest=digest)
                st['random_runs'] += 1
                note(ok, a, b, f'random dict {di} variant {vi} digest={digest}: {words} {pos}')
    print(json.dumps(st, ensure_ascii=False))
    for what, a, b in diffs[:5]:
        print('DIFFERENT:', what, '\n  old:', json.dumps(a, ensure_ascii=False)[:600], '\n  new:', json.dumps(b, ensure_ascii=False)[:600])
    sys.exit(1 if diffs else 0)


if __name__ == '__main__':
    main()
