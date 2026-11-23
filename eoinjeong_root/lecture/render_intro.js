// Render intro.html frame by frame into an MP4 (1920x1080, 60 fps, H.264), and the thumbnail images.
// usage: node eoinjeong_root/lecture/render_intro.js [OUT_DIR] [EPISODE_LABEL]
//   OUT_DIR        default eoinjeong_root/lecture/out
//   EPISODE_LABEL  default "0강 · OT" (thumbnail only)
// Every frame is drawn at an exact time: all CSS animations are paused and set to that time, so the video
// has no dropped or uneven frames. Needs ffmpeg with libx264.
'use strict';
const { chromium } = require('/opt/node-tools/node_modules/playwright');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const HERE = __dirname;
const OUT = path.resolve(process.argv[2] || path.join(HERE, 'out'));
const EP = process.argv[3] || '0강 · OT';
const FPS = 60, SECONDS = 6.0;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const url = 'file://' + path.join(HERE, 'intro.html');
  await page.goto(url);
  await page.evaluate(async () => {
    await document.fonts.load('800 128px "Nanum Myeongjo"');
    await document.fonts.load('700 104px "Noto Sans KR"');
    await document.fonts.ready;
  });
  const fontsOk = await page.evaluate(() => document.fonts.check('800 128px "Nanum Myeongjo"'));
  if (!fontsOk) throw new Error('Nanum Myeongjo did not load');

  const mp4 = path.join(OUT, 'spqr_opening_white_1080p60.mp4');
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '14', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', mp4],
    { stdio: ['pipe', 'inherit', 'inherit'] });
  const frames = Math.round(FPS * SECONDS);
  for (let f = 0; f < frames; f++) {
    const t = f * 1000 / FPS;
    await page.evaluate(t => { document.getAnimations().forEach(a => { a.pause(); a.currentTime = t; }); }, t);
    const buf = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f === Math.round(FPS * 1.0) || f === Math.round(FPS * 2.6) || f === Math.round(FPS * 3.9) || f === frames - 1)
      fs.writeFileSync(path.join(OUT, `frame_${(t / 1000).toFixed(1)}s.png`), buf);
  }
  ff.stdin.end();
  await new Promise((res, rej) => ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg ' + c))));

  // thumbnail: the finished picture with the episode label
  await page.goto(url + '?mode=thumb&ep=' + encodeURIComponent(EP));
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(OUT, 'thumbnail_full.png') });
  await browser.close();
  console.log(JSON.stringify({ mp4, frames, fps: FPS, seconds: SECONDS, thumbnail: path.join(OUT, 'thumbnail_full.png') }));
})().catch(e => { console.error(e); process.exit(1); });
