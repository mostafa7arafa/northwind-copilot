// The Northwind octopus — brand-mark geometry.
//
// Each arm is anchored at the mantle (rigid shoulder), then a sine pulse travels
// up its length: amplitude grows from zero at the shoulder to full at the tip,
// the phase advances over time (a ripple, not a swing), and the last tenth hooks
// like a real arm. Centrelines are sampled per frame and smoothed with a
// Catmull-Rom → cubic-Bézier pass, then emitted as a looping SMIL <animate>.
//
// This is the single source of truth: <BrandMark> renders it live, and the
// favicon is a frozen frame of the very same math (see scripts/gen-favicon.mjs).

const TAU = Math.PI * 2;

export interface Arm {
  bx: number; // base x (glued to the mantle)
  by: number; // base y
  dx: number; // horizontal splay from base to tip
  len: number; // arm length
  amp: number; // sway amplitude at the tip
  freq: number; // spatial frequency — how many humps ride the arm
  phase: number; // starting phase
  curl: number; // tip-hook strength
  stiff: number; // fraction of the arm that stays rigid at the shoulder
  side: -1 | 1; // mirror: left arms sway opposite the right
}

// Four arms — mirrored, each with its own personality so they coordinate
// without ever locking into sync. Four reads cleanly down to favicon size.
export const ARMS: Arm[] = [
  { bx: 15.5, by: 26.0, dx: -4.8, len: 17.5, amp: 2.3, freq: 2.3, phase: 0.0, curl: 0.9, stiff: 0.26, side: -1 },
  { bx: 20.5, by: 26.8, dx: -1.7, len: 15.5, amp: 1.7, freq: 2.45, phase: 0.95, curl: 0.7, stiff: 0.3, side: -1 },
  { bx: 27.5, by: 26.8, dx: 1.7, len: 15.5, amp: 1.7, freq: 2.6, phase: 0.95, curl: 0.7, stiff: 0.3, side: 1 },
  { bx: 32.5, by: 26.0, dx: 4.8, len: 17.5, amp: 2.3, freq: 2.75, phase: 0.0, curl: 0.9, stiff: 0.26, side: 1 },
];

const NODES = 8;
const FRAMES = 30;

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smooth = (x: number) => {
  const t = clamp01(x);
  return t * t * (3 - 2 * t);
};

/** Sample one arm's centreline at wave-time `t` (0..1), scaled by `ampNow`. */
export function armPoints(a: Arm, t: number, ampNow: number): [number, number][] {
  const pts: [number, number][] = [];
  for (let i = 0; i <= NODES; i++) {
    const s = i / NODES;
    const env = smooth((s - a.stiff) / (1 - a.stiff)); // rigid shoulder → active tip
    const theta = a.phase + TAU * t + a.freq * s; // +freq*s → pulse climbs to body
    const wave = ampNow * a.amp * env * Math.sin(theta) * a.side;
    let x = a.bx + a.dx * s + wave;
    let y = a.by + a.len * s + env * 0.3 * Math.cos(theta); // subtle vertical compression
    if (s > 0.88) {
      const c = (s - 0.88) / 0.12; // hooked tip
      x += a.side * a.curl * 1.7 * c;
      y -= c * c * 3.4 * a.curl;
    }
    pts.push([x, y]);
  }
  return pts;
}

/** Catmull-Rom → cubic Bézier, for a smooth (non-faceted) outline. */
export function toPath(p: [number, number][]): string {
  let d = `M ${p[0][0].toFixed(2)} ${p[0][1].toFixed(2)} `;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i];
    const p1 = p[i];
    const p2 = p[i + 1];
    const p3 = p[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2[0].toFixed(2)} ${p2[1].toFixed(2)} `;
  }
  return d.trim();
}

// Idle amplitude swells once per loop (still → one ripple → still); thinking
// ripples continuously.
const ampAt = (t: number, thinking: boolean) =>
  thinking ? 1 : Math.pow(Math.max(0, Math.sin(Math.PI * t)), 2);

function armMarkup(a: Arm, thinking: boolean, reduce: boolean): string {
  const dur = thinking ? 2.0 : 6.0;
  const f0 = toPath(armPoints(a, 0, ampAt(0, thinking)));
  if (reduce) return `<path class="bm-s" d="${f0}"/>`;
  const vals: string[] = [];
  for (let f = 0; f < FRAMES; f++) {
    const t = f / FRAMES;
    vals.push(toPath(armPoints(a, t, ampAt(t, thinking))));
  }
  vals.push(f0); // close the loop cleanly
  const kt = vals.map((_, i) => (i / (vals.length - 1)).toFixed(4)).join(";");
  const ks = Array(vals.length - 1).fill("0.4 0 0.6 1").join(";");
  return (
    `<path class="bm-s" d="${f0}">` +
    `<animate attributeName="d" dur="${dur}s" repeatCount="indefinite" ` +
    `calcMode="spline" keyTimes="${kt}" keySplines="${ks}" values="${vals.join(";")}"/></path>`
  );
}

/** The full inner SVG (glow + arms + mantle + eyes) as a markup string. */
export function octopusInner(thinking: boolean, reduce: boolean): string {
  return (
    `<circle class="bm-glow" cx="24" cy="21" r="13"/>` +
    `<g class="bm-arms">${ARMS.map((a) => armMarkup(a, thinking, reduce)).join("")}</g>` +
    `<g class="bm-mantle">` +
    `<path class="bm-s" d="M14 27 L15.5 15 L20 10 L28 10 L32.5 15 L34 27"/>` +
    `<g class="bm-eyes"><circle class="bm-eye" cx="20.5" cy="19" r="1.7"/><circle class="bm-eye" cx="27.5" cy="19" r="1.7"/></g>` +
    `</g>`
  );
}
