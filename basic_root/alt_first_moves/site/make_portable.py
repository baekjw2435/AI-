#!/usr/bin/env python3
"""One-address bundle of the presentation-word map, for moving it to another site.

usage: make_portable.py PARTS_DIR MAIN_DIR OUT_DIR
       make_portable.py --page-only OUT_DIR      (rebuild only index.html)
  PARTS_DIR  make_pages.py's output (part0/, part1/, …: the published parts)
  MAIN_DIR   files of the existing route map (model.json, manifest.json, catalog.json, t/k.../NN.wasm), read with the
             Artifact tool; only the tables the 77 earlier-study positions need are copied
  OUT_DIR    the bundle: index.html, site-engine.js, model.json, manifest.json, pindex.json, t/<book>/NN.wasm,
             README_KO.md, SHA256SUMS.txt

All 497 positions of the study are listed. Those verified in this study open from their own v4 certificate's table (one
book per position, as on the parts). The 77 of the earlier study open from the existing map's table of the syllable s
they were played from, with the history kept: start s, the presentation word w already used (the same line the existing
map shows after s → w). The rest are listed as undecided.
The table files are copied byte for byte; the page only fetches the files a line needs.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ALT = HERE.parent


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


PAGE_EDITS = [   # (old, new): exact replacements in presentation_body.html; each must occur once
    ("""        "<li>이 지도의 수순은 그 자리(<b>w로 t 제시</b>: w를 이미 썼고 상대가 t를 받은 자리)의 v4 증명서 하나에서만 가져옵니다. 다른 이력의 결과를 붙이지 않습니다.</li>" +
        "<li>예전 연구에서 검증한 제시 단어는 기존 ‘루트 수순 지도’의 그 수순으로 연결합니다.</li>" +""",
     """        "<li>제시 자리 " + fmt(pr.targets) + "개: <b>자체 수순 " + fmt(pr.own) + "</b> · <b>기존 수순 " + fmt(pr.old) + "</b> · <b>미확정 " + fmt(pr.left) + "</b>.</li>" +
        "<li><b>자체 수순</b>은 그 자리(<b>w로 t 제시</b>: w를 이미 썼고 상대가 t를 받은 자리)의 v4 증명서 하나에서만 가져옵니다. 다른 이력의 결과를 붙이지 않습니다.</li>" +
        "<li><b>기존 수순</b>은 예전 연구(verify_v2)에서 검증한 자리입니다. 기존 ‘루트 수순 지도’의 표를 그대로 담아, 그 증명의 사용 이력(s를 받고 w를 낸 자리) 그대로 엽니다.</li>" +"""),
    ("""      else if (it.where === "here") how = '<span class="why">이 자리의 v4 증명서 · 국면 ' + fmt(it.proof.nodes) + "개</span>";
      else if (it.where === "part") how = '<span class="why">다른 부분(' + esc(pindex.parts[it.part].name) + ")에 있음 · v4 증명서 · 국면 " + fmt(it.proof.nodes) + "개</span>";
      else if (it.where === "main") how = '<span class="why">예전 연구의 증명(verify_v2) · 기존 ‘루트 수순 지도’의 ' + esc(it.start) + " 수순으로 열림</span>";
      else how = '<span class="why">판정만 있음(이 자리의 증명서를 아직 다시 만들지 않음)</span>';""",
     """      else if (it.kind === "own") how = '<span class="why">자체 수순 · 이 자리의 v4 증명서 · 국면 ' + fmt(it.proof.nodes) + "개</span>";
      else how = '<span class="why">기존 수순 · 예전 연구의 증명(verify_v2) · ' + esc(it.start) + " 받음에서 " + esc(josa(it.words[0], "을", "를")) + " 낸 이력 그대로</span>";"""),
    ("""      var href = it.where === "here" ? "#e" + hex(t + "<" + it.words[0]) : it.where === "part" ? pindex.parts[it.part].url + "#e" + hex(t + "<" + it.words[0]) :
        it.where === "main" ? pindex.main.url + it.mainHash : "";""",
     """      var href = it.status === "open" ? "" : "#e" + hex(t + "<" + it.words[0]);"""),
    ("""(it.where === "here" ? "" : ' target="_blank" rel="noopener"')""", """"""),
    ("""    var v = VERDICT[e.result];
    var p = e.proof;""",
     """    var v = VERDICT[e.result];
    var p = e.proof, old = e.src === "old";"""),
    ("""        '<details class="proofs"><summary>근거: 이 자리의 v4 증명서 1개 (verify_v4 통과)</summary><div class="tbl"><table><tbody>' +
          "<tr><th>자리</th><td>" + esc(e.start) + " 받음 → " + esc(e.via) + " (제시) → " + esc(e.syllable) + " 받을 차례</td></tr>" +
          '<tr><th>증명 국면</th><td class="n">' + fmt(p.nodes) + "</td></tr>" +
          '<tr><th>proof_sha256</th><td class="mono">' + esc(p.sha256) + "</td></tr>" +
          "<tr><th>보관</th><td>" + (/^https:/.test(p.certificate) ? '<a href="' + esc(p.certificate) + '" target="_blank" rel="noopener">GitHub 릴리스 첨부파일</a>' : esc(p.certificate)) + "</td></tr>" +
          "<tr><th>기록</th><td>" + esc(p.source) + "</td></tr>" +
        "</tbody></table></div><p class=\\"meta\\">이 자리의 승리수 표에는 이 증명서의 수만 들어 있습니다. 다른 이력(다른 제시 단어, 빈 사전에서 받은 국면 등)의 결과는 쓰지 않습니다.</p></details>" +""",
     """        (old ?
        '<details class="proofs"><summary>근거: 기존 수순 · 예전 연구의 증명 (verify_v2 통과)</summary><div class="tbl"><table><tbody>' +
          "<tr><th>자리</th><td>" + esc(e.start) + " 받음 → " + esc(e.via) + " (제시) → " + esc(e.syllable) + " 받을 차례</td></tr>" +
          "<tr><th>증명</th><td>" + esc(p.position.join(" → ")) + " 의 증명 · 국면 " + fmt(p.nodes) + "개</td></tr>" +
          '<tr><th>proof_sha256</th><td class="mono">' + esc(p.sha256) + "</td></tr>" +
          "<tr><th>표</th><td>기존 ‘루트 수순 지도’의 ‘" + esc(p.book_name) + "’ 표 (증명 " + fmt(p.book_proofs) + "개)</td></tr>" +
        "</tbody></table></div><p class=\\"meta\\">기존 지도와 같은 표를 그대로 씁니다. 이 자리는 그 증명에서 " + esc(josa(e.start, "을", "를")) + " 받고 " + esc(josa(e.via, "을", "를")) + " 낸 이력 그대로 엽니다." +
          (p.book_proofs > 1 ? " 이 표에는 같은 계열의 증명 " + fmt(p.book_proofs) + "개가 함께 들어 있습니다(기존 지도와 같음)." : "") + "</p></details>" :
        '<details class="proofs"><summary>근거: 자체 수순 · 이 자리의 v4 증명서 1개 (verify_v4 통과)</summary><div class="tbl"><table><tbody>' +
          "<tr><th>자리</th><td>" + esc(e.start) + " 받음 → " + esc(e.via) + " (제시) → " + esc(e.syllable) + " 받을 차례</td></tr>" +
          '<tr><th>증명 국면</th><td class="n">' + fmt(p.nodes) + "</td></tr>" +
          '<tr><th>proof_sha256</th><td class="mono">' + esc(p.sha256) + "</td></tr>" +
          "<tr><th>보관</th><td>" + (/^https:/.test(p.certificate) ? '<a href="' + esc(p.certificate) + '" target="_blank" rel="noopener">GitHub 릴리스 첨부파일</a>' : esc(p.certificate)) + "</td></tr>" +
          "<tr><th>기록</th><td>" + esc(p.source) + "</td></tr>" +
        "</tbody></table></div><p class=\\"meta\\">이 자리의 승리수 표에는 이 증명서의 수만 들어 있습니다. 다른 이력(다른 제시 단어, 빈 사전에서 받은 국면 등)의 결과는 쓰지 않습니다.</p></details>") +"""),
    ("""        if (it.where !== "here") return;
        var e = { id: g.t + "<" + it.words[0], kind: "via", syllable: g.t, start: it.start, prefix: [it.words[0]], via: it.words[0], book: it.book, result: it.status, proof: it.proof };""",
     """        if (it.status === "open") return;
        var e = { id: g.t + "<" + it.words[0], kind: "via", syllable: g.t, start: it.start, prefix: [it.words[0]], via: it.words[0], book: it.book, result: it.status, proof: it.proof, src: it.kind };"""),
    ("""      "<span>이 부분(" + esc(pindex.parts[pindex.self].name) + "): 제시 자리 " + fmt(books) + "개 · 승리수 표 " + fmt(recs) + "항목 · 모든 표는 그 자리의 증명서(C++ verify_v4 통과)에서 뽑았습니다.</span>" +
      "<span>" + pindex.parts.map(function (p, i) { return i === pindex.self ? "<b>" + esc(p.name) + "</b>" : '<a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + esc(p.name) + "</a>"; }).join(" · ") +
      ' · <a href="' + esc(pindex.main.url) + '" target="_blank" rel="noopener">루트 수순 지도</a></span>' +""",
     """      "<span>표 " + fmt(books) + "개 · 승리수 표 " + fmt(recs) + "항목 · 자체 수순의 표는 그 자리의 v4 증명서(C++ verify_v4 통과)에서, 기존 수순의 표는 기존 ‘루트 수순 지도’에서 그대로 가져왔습니다.</span>" +"""),
]


def main():
    parts, main_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    if out.exists():
        shutil.rmtree(out)
    (out / 't').mkdir(parents=True)
    model = json.loads((main_dir / 'model.json').read_text(encoding='utf-8'))
    main_man = json.loads((main_dir / 'manifest.json').read_text(encoding='utf-8'))
    main_cat = json.loads((main_dir / 'catalog.json').read_text(encoding='utf-8'))
    main_books = {b['id']: b for b in main_man['books']}
    fresh = {e['start']: e for e in main_cat['entries'] if e['kind'] == 'fresh'}
    targets = {t['id']: t for t in json.loads((ALT / 'targets.json').read_text(encoding='utf-8'))['targets']}
    books, copied = [], 0
    # 1. every part's own books, file for file
    nparts = sum(1 for d in parts.iterdir() if d.is_dir() and d.name.startswith('part'))
    for k in range(nparts):
        man = json.loads((parts / f'part{k}' / 'manifest.json').read_text(encoding='utf-8'))
        for b in man['books']:
            for f in b['files']:
                (out / f['path']).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(parts / f'part{k}' / f['path'], out / f['path']); copied += 1
            books.append(b)
    pindex = json.loads((parts / 'part0' / 'pindex.json').read_text(encoding='utf-8'))
    # 2. groups: own / old / open, with the existing map's book for the 77
    need = set()
    own = old = left = 0
    for g in pindex['groups']:
        items = []
        for it in g['items']:
            r = {'id': it['id'], 'start': it['start'], 'words': it['words'], 'status': it['status']}
            if it['where'] in ('here', 'part'):
                r.update(kind='own', book=it['book'], proof=it['proof']); own += 1
            elif it['where'] == 'main':
                t = targets[it['id']]
                pr = t['existing']['proof']
                mb = main_books[it['mainBook']]      # the book holding the proof of exactly this position (make_pages.main_line)
                r.update(kind='old', book=mb['id'],
                         proof={'position': pr['position'], 'nodes': pr['nodes'], 'sha256': pr['sha256'], 'verifier': t['existing'].get('verifier'),
                                'book_name': mb['name'], 'book_proofs': len(mb['proofs'])})
                need.add(mb['id']); old += 1
            else:
                r.update(kind='open'); left += 1
            items.append(r)
        g['items'] = items
    for bid in sorted(need):
        b = main_books[bid]
        for f in b['files']:
            (out / f['path']).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(main_dir / f['path'], out / f['path']); copied += 1
        books.append(b)
    pindex = {'format': 'presentation-map-portable-1', 'progress': {**pindex['progress'], 'own': own, 'old': old}, 'groups': pindex['groups']}
    pindex['progress']['left'] = left
    manifest = {'format': 'route-site-1', 'dictionary_sha256': model['dictionary_sha256'], 'encoding': 'wasm-custom', 'books': books,
                'total_entries': sum(b['entries'] for b in books), 'total_bytes': sum(f['bytes'] for b in books for f in b['files'])}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'pindex.json').write_text(json.dumps(pindex, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    shutil.copyfile(main_dir / 'model.json', out / 'model.json')
    shutil.copyfile(ALT.parent / 'route-site' / 'site-engine.js', out / 'site-engine.js')
    write_page(out)
    print(json.dumps({'books': len(books), 'own_books': len(books) - len(need), 'existing_map_books': len(need), 'table_files': copied,
                      'entries': manifest['total_entries'], 'own': own, 'old': old, 'open': left}))


def write_page(out):
    body = (HERE / 'presentation_body.html').read_text(encoding='utf-8')
    for a, b in PAGE_EDITS:
        assert body.count(a) == 1, a[:80]
        body = body.replace(a, b)
    head = (HERE / 'presentation_head.html').read_text(encoding='utf-8')
    style = (HERE / 'style.css.part').read_text(encoding='utf-8')
    # a complete document, so any static host can serve it (the artifact service used to add this skeleton)
    reset = (':root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
             'html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif}'
             'img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}')
    page = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            '<style>' + reset + '</style>\n' + head +
            '<style>\n' + style.split('<style>', 1)[-1].rsplit('</style>', 1)[0] + '</style>\n</head>\n<body>\n' + body + '\n</body>\n</html>\n')
    (out / 'index.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--page-only']:      # rebuild only index.html of an existing bundle
        write_page(Path(sys.argv[2]))
    else:
        main()
