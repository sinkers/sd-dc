// Number formatting shared by every view. One place, so a kW reads the same in
// a dial, a card and a chart legend.

export const kw = (v) => (v == null ? '–' : `${fix(v, Math.abs(v) >= 100 ? 0 : 1)}`);
export const pct = (v) => (v == null ? '–' : `${fix(v, 0)}`);

export function money(v, { sign = false } = {}) {
  if (v == null || !Number.isFinite(v)) return '–';
  const s = sign && v > 0 ? '+' : v < 0 ? '−' : '';
  const a = Math.abs(v);
  const body = a >= 10000 ? Math.round(a).toLocaleString('en-AU') : a >= 100 ? a.toFixed(0) : a.toFixed(2);
  return `${s}$${body}`;
}

export function price(v) {
  if (v == null) return '–';
  const a = Math.abs(v);
  return `${v < 0 ? '−' : ''}$${a >= 1000 ? Math.round(a).toLocaleString('en-AU') : a.toFixed(0)}`;
}

export function fix(v, places = 1) {
  if (v == null || !Number.isFinite(v)) return '–';
  const r = Number(v.toFixed(places));
  return (Object.is(r, -0) ? 0 : r).toLocaleString('en-AU', { minimumFractionDigits: places, maximumFractionDigits: places });
}

export function minutes(v) {
  if (v == null || !Number.isFinite(v) || v >= 9999) return '–';
  if (v >= 120) return `${fix(v / 60, 1)} h`;
  return `${fix(v, 0)} min`;
}

/** Signed log scale for prices that run from −$250 to $13,000 on one axis. */
export const symlog = {
  f: (x) => Math.sign(x) * Math.log10(1 + Math.abs(x) / 10),
  inv: (y) => Math.sign(y) * 10 * (10 ** Math.abs(y) - 1),
};
