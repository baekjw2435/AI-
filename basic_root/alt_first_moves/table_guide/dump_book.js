// dump_book.js SITE_DIR BOOK_ID OUT.bin ENGINE.js
// Unpacks one book of the route site (its winning-move table files) with the site engine's own decoder, after
// checking every file against the sha256 in SITE_DIR/manifest.json, into a flat file for solver_v5_table:
//   'RTG1', u32 files; per file: u32 core_lo, u32 core_hi, u32 width, u32 n, u64 keys[n] (LE), u16 groups[n] (LE)
// keys are the top `width` bits of the engine's 48-bit key, as stored; groups are site group numbers.
"use strict";
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const [dir, bookId, out, enginePath] = process.argv.slice(2);
const E = require(path.resolve(enginePath));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
function unwasm(b) {   // the site's packing: one custom section of an empty WebAssembly module
  const u = new Uint8Array(b.buffer, b.byteOffset, b.length); let p = 9;
  const leb = () => { let r = 0, s = 1, x; do { x = u[p++]; r += (x & 0x7f) * s; s *= 128; } while (x & 0x80); return r; };
  const size = leb(), end = p + size, nl = leb(); p += nl;
  if (u[0] !== 0 || u[1] !== 0x61 || end !== u.length) throw new Error("bad wasm wrap");
  return b.buffer.slice(b.byteOffset + p, b.byteOffset + end);
}
const book = manifest.books.find((b) => b.id === bookId);
if (!book) throw new Error("no book " + bookId);
const parts = [];
const head = Buffer.alloc(8); head.write("RTG1", 0, "ascii"); head.writeUInt32LE(book.files.length, 4); parts.push(head);
let entries = 0;
for (const f of book.files) {
  const raw = fs.readFileSync(path.join(dir, f.path));
  const payload = manifest.encoding === "wasm-custom" ? unwasm(raw) : raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.length);
  if (payload.byteLength !== f.bytes) throw new Error("size differs: " + f.path);   // f.bytes: the RSB1 payload, as the engine checks
  const sha = crypto.createHash("sha256").update(Buffer.from(payload)).digest("hex");
  if (f.sha256 && sha !== f.sha256) throw new Error("sha256 differs: " + f.path);
  const T = E.decode(payload);
  if (T.n !== f.n) throw new Error("entry count differs: " + f.path);
  const width = 48 - Math.round(Math.log2(T.shift));
  const h = Buffer.alloc(16);
  h.writeUInt32LE(f.core_lo, 0); h.writeUInt32LE(f.core_hi, 4); h.writeUInt32LE(width, 8); h.writeUInt32LE(T.n, 12);
  const kb = Buffer.alloc(8 * T.n), gb = Buffer.alloc(2 * T.n);
  for (let i = 0; i < T.n; i++) { kb.writeBigUInt64LE(BigInt(T.keys[i]), 8 * i); gb.writeUInt16LE(T.groups[i], 2 * i); }
  parts.push(h, kb, gb);
  entries += T.n;
}
fs.writeFileSync(out, Buffer.concat(parts));
console.log(JSON.stringify({ book: bookId, name: book.name, files: book.files.length, entries, proofs: book.proofs.map((p) => p.id) }));
