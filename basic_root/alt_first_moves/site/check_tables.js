// check_tables.js DIR : decode every table file of DIR/manifest.json with the site engine's own decoder and compare
// the decoded keys and groups with the sha256 site_books.py recorded (content_sha256 over u64 keys + u16 groups).
"use strict";
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const dir = path.resolve(process.argv[2]), enginePath = process.argv[3];
const E = require(path.resolve(enginePath));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
function unwasm(b) {   // the site's packing: one custom section of an empty WebAssembly module
  const u = new Uint8Array(b.buffer, b.byteOffset, b.length); let p = 9;
  const leb = () => { let r = 0, s = 1, x; do { x = u[p++]; r += (x & 0x7f) * s; s *= 128; } while (x & 0x80); return r; };
  const size = leb(), end = p + size, nl = leb(); p += nl;
  if (u[0] !== 0 || u[1] !== 0x61 || end !== u.length) throw new Error("bad wasm wrap");
  return b.buffer.slice(b.byteOffset + p, b.byteOffset + end);
}
const load = (dir, p, manifest) => { const b = fs.readFileSync(path.join(dir, p)); return manifest.encoding === "wasm-custom" ? unwasm(b) : b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
let files = 0, bad = 0;
for (const b of manifest.books) for (const f of b.files) {
  const T = E.decode(load(dir, f.path, manifest));
  const kb = Buffer.alloc(8 * T.n), gb = Buffer.alloc(2 * T.n);
  for (let i = 0; i < T.n; i++) { kb.writeBigUInt64LE(BigInt(T.keys[i]), 8 * i); gb.writeUInt16LE(T.groups[i], 2 * i); }
  const h = crypto.createHash("sha256").update(kb).update(gb).digest("hex");
  if (T.n !== f.n || h !== f.content_sha256) { bad++; console.log("MISMATCH", f.path); }
  files++;
}
console.log(JSON.stringify({ files, bad }));
process.exit(bad ? 1 : 0);
