// Regenerate the favicon from the octopus math so it can never drift from the
// live <BrandMark>. Writes app/icon.svg (browser tab) and app/apple-icon.svg.
// Run:  node scripts/gen-favicon.mjs   (from frontend/)
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const TAU = Math.PI * 2;
const ARMS = [
  { bx: 15.5, by: 26.0, dx: -4.8, len: 17.5, amp: 2.3, freq: 2.3, phase: 0.0, curl: 0.9, stiff: 0.26, side: -1 },
  { bx: 20.5, by: 26.8, dx: -1.7, len: 15.5, amp: 1.7, freq: 2.45, phase: 0.95, curl: 0.7, stiff: 0.3, side: -1 },
  { bx: 27.5, by: 26.8, dx: 1.7, len: 15.5, amp: 1.7, freq: 2.6, phase: 0.95, curl: 0.7, stiff: 0.3, side: 1 },
  { bx: 32.5, by: 26.0, dx: 4.8, len: 17.5, amp: 2.3, freq: 2.75, phase: 0.0, curl: 0.9, stiff: 0.26, side: 1 },
];
const NODES = 8;
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const smooth = (x) => { const t = clamp01(x); return t * t * (3 - 2 * t); };

function armPoints(a, t, ampNow) {
  const pts = [];
  for (let i = 0; i <= NODES; i++) {
    const s = i / NODES;
    const env = smooth((s - a.stiff) / (1 - a.stiff));
    const theta = a.phase + TAU * t + a.freq * s;
    const wave = ampNow * a.amp * env * Math.sin(theta) * a.side;
    let x = a.bx + a.dx * s + wave;
    let y = a.by + a.len * s + env * 0.3 * Math.cos(theta);
    if (s > 0.88) { const c = (s - 0.88) / 0.12; x += a.side * a.curl * 1.7 * c; y -= c * c * 3.4 * a.curl; }
    pts.push([x, y]);
  }
  return pts;
}
function toPath(p) {
  let d = `M ${p[0][0].toFixed(2)} ${p[0][1].toFixed(2)} `;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2[0].toFixed(2)} ${p2[1].toFixed(2)} `;
  }
  return d.trim();
}

// A frozen frame with a little life in the arms (mid-ripple, moderate amplitude).
const T = 0.16, AMP = 1.4;
const arms = ARMS.map((a) => `<path d="${toPath(armPoints(a, T, AMP))}"/>`).join("");

const svg = (px) => `<svg xmlns="http://www.w3.org/2000/svg" width="${px}" height="${px}" viewBox="0 0 48 48">
  <rect x="1" y="1" width="46" height="46" rx="11" fill="#0b0d12"/>
  <g fill="none" stroke="#4f8cff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
    ${arms}
    <path d="M14 27 L15.5 15 L20 10 L28 10 L32.5 15 L34 27"/>
  </g>
  <circle cx="20.5" cy="19" r="1.9" fill="#4f8cff"/>
  <circle cx="27.5" cy="19" r="1.9" fill="#4f8cff"/>
</svg>
`;

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, "..", "app");
writeFileSync(join(app, "icon.svg"), svg(48));
writeFileSync(join(app, "apple-icon.svg"), svg(180));
console.log("wrote app/icon.svg and app/apple-icon.svg");
