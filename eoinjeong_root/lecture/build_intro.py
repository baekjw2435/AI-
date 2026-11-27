#!/usr/bin/env python3
"""Write eoinjeong_root/lecture/intro.html: the white SPQR opening (about 6 s) and the thumbnail layout.

usage: python3 eoinjeong_root/lecture/build_intro.py
  intro.html                    the opening animation (CSS animations only, so a renderer can step it frame by frame)
  intro.html?mode=thumb&ep=...  the last frame as a thumbnail, with the episode label (e.g. "0강 · OT") under the title
Render: node eoinjeong_root/lecture/render_intro.js  (MP4 and thumbnail images)
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 640, 360
CX, CY, RX, RY = 320, 176, 268, 150
T0, TSPAN = 0.06, 2.44          # stem parameter range (bottom -> top)
DRAW_START, DRAW_DUR = 0.25, 1.45   # seconds: stem drawing


def pt(t, side):
    x = CX - RX * math.sin(t)
    y = CY + RY * math.cos(t)
    return (x if side < 0 else W - x, y)


def tang(t, side):
    dx, dy = -RX * math.cos(t), -RY * math.sin(t)
    if side > 0:
        dx = -dx
    return math.degrees(math.atan2(dy, dx))


def when(t):
    """Time at which the drawing stem reaches parameter t."""
    return DRAW_START + DRAW_DUR * (t - T0) / TSPAN


def wreath_svg():
    o = ['<svg class="wreath" viewBox="0 0 640 360" aria-label="청동빛 월계관">',
         '<defs><linearGradient id="lf" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#DDBB6A"/>'
         '<stop offset="1" stop-color="#7A5520"/></linearGradient></defs>']
    # ribbon first (it sits under the stems)
    o.append('<g class="ribbon"><path d="M314 322L290 352L301 355L318 327Z" fill="#9E2323"/>'
             '<path d="M326 322L350 352L339 355L322 327Z" fill="#9E2323"/></g>')
    for side in (-1, 1):
        ts = [T0 + i * TSPAN / 48 for i in range(49)]
        d = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in (pt(t, side) for t in ts))
        o.append(f'<path class="stem" pathLength="1" d="{d}"/>')
        n = 10
        for k in range(n):
            t = 0.32 + k * (2.38 - 0.32) / (n - 1)
            x, y = pt(t, side)
            a = tang(t, side)
            s = 48 - k * 1.8
            leaf = f'M0 0Q{s / 2:.1f} {-s * 0.3:.1f} {s:.1f} 0Q{s / 2:.1f} {s * 0.3:.1f} 0 0Z'
            for j, da in enumerate((38, -38)):
                o.append(f'<g transform="translate({x:.1f} {y:.1f}) rotate({a + da:.1f})">'
                         f'<path class="leaf" style="--d:{when(t) + 0.06 * j:.3f}s" d="{leaf}"/></g>')
            if k in (2, 5, 8):
                bx = x + (-12 if side < 0 else 12) * math.sin(t)
                by = y + 12 * math.cos(t)
                o.append(f'<circle class="berry" style="--d:{when(t) + 0.18:.3f}s" cx="{bx:.1f}" cy="{by:.1f}" r="5.5"/>')
        x, y = pt(2.5, side)
        a = tang(2.5, side)
        o.append(f'<g transform="translate({x:.1f} {y:.1f}) rotate({a:.1f})">'
                 f'<path class="leaf" style="--d:{when(2.5):.3f}s" d="M0 0Q15 -9 30 0Q15 9 0 0Z"/></g>')
    o.append('<circle class="knot" cx="320" cy="323" r="9"/>')
    o.append('</svg>')
    return ''.join(o)


STAR = 'M0 -20 C2 -6 6 -2 20 0 C6 2 2 6 0 20 C-2 6 -6 2 -20 0 C-6 -2 -2 -6 0 -20Z'
# (x, y, start seconds, size): the wreath tips, the lower wreath, and beside the red '전'
SPARKLES = [(780, 249, 4.55, 1.0), (1140, 249, 4.75, 0.9), (1702, 672, 4.35, 0.8), (688, 520, 4.9, 0.6), (1236, 470, 5.05, 0.7)]

CSS = r'''
:root { --ink:#18202C; --ink-soft:#4A5566; --bronze:#7A5A22; --gold:#C9A14E; --red:#8E1C1C;
  --display:'Nanum Myeongjo','AppleMyungjo','Batang',Georgia,serif; --body:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1920px; height:1080px; overflow:hidden; }
body { background:#FFFFFF; font-family:var(--body); }
.stage { position:relative; width:1920px; height:1080px; overflow:hidden;
  background: radial-gradient(ellipse 70% 75% at 50% 46%, #FFFFFF 0%, #FCFBF8 55%, #F1EEE7 100%);
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.light { position:absolute; inset:0; background: radial-gradient(ellipse 38% 34% at 50% 34%, rgba(232,206,140,.20), rgba(232,206,140,0) 70%);
  animation: fade 1600ms ease-out 600ms both; }
@keyframes fade { from { opacity:0; } to { opacity:1; } }

.crest { position:relative; width:720px; height:405px; }
.wreath { position:absolute; inset:0; width:720px; height:405px; overflow:visible; filter: drop-shadow(0 6px 8px rgba(90,62,20,.16)); }
.stem { fill:none; stroke:#8C6A2C; stroke-width:3; stroke-linecap:round; stroke-dasharray:1; stroke-dashoffset:0;
  animation: draw 1450ms cubic-bezier(.45,.05,.35,1) 250ms both; }
@keyframes draw { from { stroke-dashoffset:1; } to { stroke-dashoffset:0; } }
.leaf { fill:url(#lf); stroke:#5E4419; stroke-width:1; transform-box:fill-box; transform-origin:0% 50%;
  animation: leafIn 620ms cubic-bezier(.2,.9,.3,1.35) both; animation-delay:var(--d); }
@keyframes leafIn { from { transform:scale(0) rotate(-28deg); opacity:0; } 40% { opacity:1; } to { transform:scale(1) rotate(0deg); opacity:1; } }
.berry { fill:#A9802F; transform-box:fill-box; transform-origin:50% 50%; animation: pop 420ms cubic-bezier(.2,.9,.3,1.6) both; animation-delay:var(--d); }
@keyframes pop { from { transform:scale(0); opacity:0; } to { transform:scale(1); opacity:1; } }
.ribbon { transform-box:fill-box; transform-origin:50% 0%; animation: unfurl 700ms cubic-bezier(.2,.8,.2,1) 150ms both; }
@keyframes unfurl { from { transform:scaleY(0); opacity:0; } to { transform:scaleY(1); opacity:1; } }
.knot { fill:#B32A2A; stroke:#9A7330; stroke-width:1.5; transform-box:fill-box; transform-origin:50% 50%; animation: pop 500ms cubic-bezier(.2,.9,.3,1.6) 100ms both; }

.spqr { position:absolute; left:0; top:150px; width:720px; text-align:center; padding-left:36px;
  font-family:var(--display); font-weight:800; font-size:84px; line-height:1.1; letter-spacing:36px;
  background: linear-gradient(100deg, #6E4E1A 0%, #9C7A35 30%, #B08A3C 44%, #F3E1A8 50%, #B08A3C 56%, #9C7A35 70%, #6E4E1A 100%);
  background-size:300% 100%; background-position:0% 0%; -webkit-background-clip:text; background-clip:text; color:transparent;
  filter: drop-shadow(0 2px 3px rgba(110,78,26,.22));
  animation: spqrIn 1100ms cubic-bezier(.2,.7,.2,1) 1300ms both, shine 1500ms ease-in-out 2300ms both; }
@keyframes spqrIn { from { opacity:0; letter-spacing:72px; filter: blur(14px) drop-shadow(0 2px 3px rgba(110,78,26,0)); }
  to { opacity:1; letter-spacing:36px; filter: blur(0px) drop-shadow(0 2px 3px rgba(110,78,26,.22)); } }
@keyframes shine { from { background-position:100% 0%; } to { background-position:0% 0%; } }

.rule { width:460px; height:2px; margin:26px 0 42px; background: linear-gradient(90deg, rgba(154,115,48,0), #9A7330 18%, #C9A14E 50%, #9A7330 82%, rgba(154,115,48,0));
  animation: grow 1000ms cubic-bezier(.3,.7,.2,1) 2000ms both; }
@keyframes grow { from { transform:scaleX(0); opacity:0; } to { transform:scaleX(1); opacity:1; } }

.title { position:relative; display:flex; align-items:center; gap:40px; }
.word { display:flex; gap:6px; }
.ch { font-family:var(--display); font-weight:800; font-size:128px; line-height:1.1; color:var(--ink);
  text-shadow: 0 4px 14px rgba(24,32,44,.12);
  animation: chIn 900ms cubic-bezier(.16,.84,.24,1) both; animation-delay: calc(2450ms + var(--i) * 105ms); }
@keyframes chIn { from { opacity:0; transform: translateY(56px) rotate(-7deg) scale(.82); filter: blur(12px); }
  to { opacity:1; transform: translateY(0) rotate(0deg) scale(1); filter: blur(0px); } }
.ch.tail { animation: chIn 900ms cubic-bezier(.16,.84,.24,1) both, ember 800ms ease-out both; animation-delay: calc(2450ms + var(--i) * 105ms), 3950ms; color:var(--red);
  text-shadow: 0 4px 18px rgba(142,28,28,.22); }
@keyframes ember { from { color:var(--ink); text-shadow: 0 4px 14px rgba(24,32,44,.12); } to { color:var(--red); text-shadow: 0 4px 18px rgba(142,28,28,.22); } }
.dia { width:18px; height:18px; background:#9A7330; transform: rotate(45deg); animation: diaIn 600ms ease-out 3100ms both; }
@keyframes diaIn { from { opacity:0; transform: rotate(45deg) scale(0); } to { opacity:1; transform: rotate(45deg) scale(1); } }
/* gold sheen through the dark letters only: lighten keeps the white page white */
.sheen { position:absolute; top:-10px; bottom:-10px; left:-200px; width:240px; mix-blend-mode:lighten; pointer-events:none;
  background: linear-gradient(100deg, rgba(214,178,98,0) 0%, rgba(214,178,98,.95) 50%, rgba(214,178,98,0) 100%);
  opacity:0; animation: sweep 1100ms ease-in-out 3650ms both; }
@keyframes sweep { 0% { opacity:0; transform: translateX(0px) skewX(-16deg); } 12% { opacity:1; } 88% { opacity:1; }
  100% { opacity:0; transform: translateX(1720px) skewX(-16deg); } }

.sub { margin-top:44px; font-size:34px; letter-spacing:14px; padding-left:14px; color:var(--ink-soft); animation: rise 900ms ease-out 4250ms both; }
@keyframes rise { from { opacity:0; transform: translateY(16px); } to { opacity:1; transform: translateY(0); } }

.spark { position:absolute; width:40px; height:40px; margin:-20px 0 0 -20px; }
.spark svg { width:40px; height:40px; overflow:visible; animation: twinkle 900ms ease-in-out both; animation-delay: var(--d); }
.spark path { fill:#E3C27A; }
@keyframes twinkle { 0% { transform: scale(0) rotate(0deg); opacity:0; } 40% { transform: scale(var(--s)) rotate(45deg); opacity:1; }
  100% { transform: scale(0) rotate(90deg); opacity:0; } }

/* thumbnail: the finished picture, a bit higher, with the episode label under the title */
body.thumb * { animation: none !important; }
body.thumb .sheen, body.thumb .spark, body.thumb .sub { display:none; }
body.thumb .stage { justify-content:flex-start; padding-top:96px; }
body.thumb .crest { transform: scale(.86); margin:-28px 0 -28px; }
body.thumb .rule { margin:18px 0 34px; }
body.thumb .ep { display:block; }
.ep { display:none; margin-top:56px; padding:18px 64px 24px; border-radius:20px; background:var(--red); color:#FBF3E4;
  font-family:var(--body); font-weight:700; font-size:104px; line-height:1.15; letter-spacing:4px; box-shadow: 0 10px 30px rgba(142,28,28,.25); }
'''


def main():
    chars = '표준사전 어인정 루트전'
    words, i = [], 0
    for w in chars.split():
        spans = []
        for c in w:
            cls = 'ch tail' if i == 9 else 'ch'
            spans.append(f'<span class="{cls}" style="--i:{i}">{c}</span>')
            i += 1
        words.append('<div class="word">' + ''.join(spans) + '</div>')
    title = words[0] + '<span class="dia"></span>' + words[1] + '<span class="dia"></span>' + words[2]
    sparks = ''.join(f'<div class="spark" style="left:{x}px;top:{y}px;--d:{d}s;--s:{s}"><svg viewBox="-20 -20 40 40"><path d="{STAR}"/></svg></div>'
                     for x, y, d, s in SPARKLES)
    html = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>SPQR 오프닝</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nanum+Myeongjo:wght@800&family=Noto+Sans+KR:wght@400;700&display=block">
<style>{CSS}</style></head>
<body><div class="stage"><div class="light"></div>
<div class="crest">{wreath_svg()}<div class="spqr">SPQR</div></div>
<div class="rule"></div>
<div class="title">{title}<div class="sheen"></div></div>
<div class="sub">끝말잇기 강의</div>
<div class="ep" id="ep">0강 · OT</div>
{sparks}
</div>
<script>
const q = new URLSearchParams(location.search);
if (q.get('mode') === 'thumb') document.body.classList.add('thumb');
if (q.get('ep')) document.getElementById('ep').textContent = q.get('ep');
</script></body></html>
'''
    (HERE / 'intro.html').write_text(html, encoding='utf-8')
    print('intro.html', len(html), 'bytes')


if __name__ == '__main__':
    main()
