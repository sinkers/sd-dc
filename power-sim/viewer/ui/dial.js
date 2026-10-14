// Arc gauge. A 270° sweep, value arc drawn from the minimum, or from zero for a
// signed quantity such as BESS power, so the direction of flow is the first
// thing you see.
//
//   const d = dial({ label: 'State of charge', unit: '%', min: 0, max: 100,
//                    bands: [{ from: 0, to: 10 }, { from: 95, to: 100 }] });
//   el.append(d.el); d.set(63.2, 'charge');

const NS = 'http://www.w3.org/2000/svg';
const SWEEP = 135; // degrees either side of straight up
const CX = 66, CY = 62, R = 46;

function svg(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

function pt(deg, r = R) {
  const a = (deg * Math.PI) / 180;
  return [CX + r * Math.sin(a), CY - r * Math.cos(a)];
}

function arc(a0, a1, r = R) {
  if (Math.abs(a1 - a0) < 0.01) return '';
  const [lo, hi] = a0 < a1 ? [a0, a1] : [a1, a0];
  const [x0, y0] = pt(lo, r), [x1, y1] = pt(hi, r);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${hi - lo > 180 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}

export function dial({ label, unit = '', min = 0, max = 100, format = (v) => v.toFixed(0), centerZero = false,
                       bands = [], scale = null, limLabels = null } = {}) {
  const el = document.createElement('div');
  el.className = 'dial';
  const s = svg('svg', { viewBox: '0 0 132 112', role: 'img' }, el);
  const title = svg('title', {}, s);
  svg('path', { d: arc(-SWEEP, SWEEP), class: 'track', 'stroke-width': 10, fill: 'none' }, s);
  const bandG = svg('g', {}, s);
  const val = svg('path', { class: 'value-arc', 'stroke-width': 10, fill: 'none', 'stroke-linecap': 'butt' }, s);
  svg('path', { d: arc(-SWEEP, SWEEP, R + 6.5), class: 'rim', 'stroke-width': 1, fill: 'none' }, s);
  const needle = svg('line', { class: 'needle' }, s);
  const num = svg('text', { x: CX, y: CY + 6, 'text-anchor': 'middle', class: 'num' }, s);
  const un = svg('text', { x: CX, y: CY + 21, 'text-anchor': 'middle', class: 'unit' }, s);
  un.textContent = unit;
  const lo = svg('text', { x: pt(-SWEEP, R)[0] + 2, y: 108, 'text-anchor': 'middle', class: 'lim' }, s);
  const hi = svg('text', { x: pt(SWEEP, R)[0] - 2, y: 108, 'text-anchor': 'middle', class: 'lim' }, s);
  const cap = document.createElement('div');
  cap.className = 'cap';
  cap.textContent = label;
  el.append(cap);

  const f = scale?.f ?? ((x) => x);
  let range = { min, max };

  const angle = (v) => {
    const a = f(range.min), b = f(range.max);
    const t = Math.min(1, Math.max(0, (f(v) - a) / (b - a || 1)));
    return -SWEEP + t * 2 * SWEEP;
  };

  function setRange(nextMin = range.min, nextMax = range.max, nextBands = bands) {
    range = { min: nextMin, max: nextMax };
    const [lmin, lmax] = limLabels ? limLabels(range) : [format(range.min), format(range.max)];
    lo.textContent = lmin;
    hi.textContent = lmax;
    bandG.replaceChildren();
    for (const b of nextBands) {
      svg('path', { d: arc(angle(b.from), angle(b.to), R - 8), class: 'band-arc', 'stroke-width': 3, fill: 'none' }, bandG);
    }
  }
  setRange();

  function set(v, cls = '') {
    if (v == null || !Number.isFinite(v)) {
      num.textContent = '–';
      val.setAttribute('d', '');
      return;
    }
    const origin = centerZero ? angle(0) : -SWEEP;
    const a = angle(v);
    val.setAttribute('d', arc(origin, a));
    val.setAttribute('class', `value-arc ${cls}`);
    const [x0, y0] = pt(a, R - 13), [x1, y1] = pt(a, R + 6);
    needle.setAttribute('x1', x0); needle.setAttribute('y1', y0);
    needle.setAttribute('x2', x1); needle.setAttribute('y2', y1);
    num.textContent = format(v);
    title.textContent = `${label}: ${format(v)} ${unit}`;
  }

  return { el, set, setRange };
}
