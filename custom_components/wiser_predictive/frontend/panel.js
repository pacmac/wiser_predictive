/* Wiser Predictive panel: inside, outside and heating for one room, with a summary in words (docs/SPEC.md, VISUALISATION).
   Home Assistant passes `hass`, `narrow` and `panel` to the element. The data comes from the integration's websocket
   command `wiser_predictive/chart`; this file only draws it. Colours follow the Home Assistant theme. */

const STYLE = `
:host{ display:block; box-sizing:border-box; min-height:100%; padding:16px max(16px,env(safe-area-inset-right,0px)) 32px max(16px,env(safe-area-inset-left,0px));
  --bg:var(--primary-background-color,#f4f6f4); --panel:var(--card-background-color,#fff); --ink:var(--primary-text-color,#18211f);
  --muted:var(--secondary-text-color,#5a6763); --grid:var(--divider-color,#e1e7e4); --axis:#b9c4bf;
  --in:#123f8c; --out:#0b7a85; --heat:rgba(214,96,48,.20); --heat-ink:#b8481f; --fc:rgba(11,122,133,.06);
  --btn:rgba(127,140,135,.16); --btn-on:var(--ink); --btn-on-ink:var(--panel);
  background:var(--bg); color:var(--ink); font-family:var(--paper-font-body1_-_font-family,"Roboto",system-ui,sans-serif); font-size:15px; line-height:1.5; }
:host([dark]){ --in:#7ea6ff; --out:#4cc4cf; --heat:rgba(238,122,92,.22); --heat-ink:#ee7a5c; --fc:rgba(76,196,207,.07); --axis:#46544f; }
main{ max-width:1100px; margin:0 auto; display:flex; flex-direction:column; gap:16px; }
.bar{ display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; justify-content:space-between; }
.left{ display:flex; align-items:center; gap:8px; min-width:0; }
h1{ font-size:22px; font-weight:500; margin:0; }
.ctl{ display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; }
.btns{ display:flex; gap:6px; }
button,select{ font:inherit; color:var(--ink); background:var(--btn); border:0; border-radius:6px; padding:6px 14px; cursor:pointer; }
button{ font-weight:500; } button[aria-pressed="true"]{ background:var(--btn-on); color:var(--btn-on-ink); }
button:focus-visible,select:focus-visible{ outline:2px solid var(--in); outline-offset:2px; }
.story{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
.story > div{ background:var(--panel); border-radius:8px; padding:12px 14px; min-width:0; }
.story .k{ font-size:13px; font-weight:600; display:flex; align-items:center; gap:8px; }
.story .k i{ width:18px; border-top:3px solid; }
.story .v{ font-size:19px; font-weight:500; margin-top:2px; font-variant-numeric:tabular-nums; }
.story .d{ color:var(--muted); font-size:13px; }
#readout{ background:var(--panel); border-radius:6px; padding:8px 12px; min-height:2.6em; font-family:ui-monospace,"Roboto Mono",monospace; font-size:13px; font-variant-numeric:tabular-nums; }
#chart{ background:var(--panel); border-radius:8px; padding:8px 0; }
svg{ display:block; width:100%; touch-action:pan-y; }
svg text{ fill:var(--muted); font-size:12px; font-family:inherit; }
svg text.pt{ fill:var(--ink); font-weight:600; font-size:14px; }
svg text.heat{ fill:var(--heat-ink); font-weight:600; font-size:11px; }
svg text.mono{ font-family:ui-monospace,"Roboto Mono",monospace; }
.note{ color:var(--muted); font-size:13px; max-width:80ch; margin:0; }
.empty{ padding:28px 16px; color:var(--muted); text-align:center; }
`;

const MERGE_GAP = 20 * 60;  /* seconds. Wiser's boost and heating spans are merged when less than 20 min apart: a boost lasts 14-15 min, so one heat-up is one band. */
const LEFT = 46, RIGHT = 12, TITLE = 24, GAP = 14, AXIS = 30;

const fmtT = (t, o) => new Date(t * 1000).toLocaleString([], o);
const hhmm = t => fmtT(t, { hour: '2-digit', minute: '2-digit', hour12: false });
const num = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? '–' : v.toFixed(d);

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map(m => m * p).find(s => s >= raw) || raw, out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}
function visible(data, x0, x1) {
  const out = []; let before = null;
  for (const p of data) { if (p[0] < x0) before = p; else if (p[0] <= x1) out.push(p); }
  if (before) out.unshift([x0, before[1]]);
  return out;
}
function at(data, t, step) {
  let lo = 0, hi = data.length - 1, i = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (data[m][0] <= t) { i = m; lo = m + 1; } else hi = m - 1; }
  if (i < 0) return null;
  if (i === data.length - 1) return t - data[i][0] > 2 * 86400 ? null : data[i][1];
  if (step) return data[i][1];
  const [t0, v0] = data[i], [t1, v1] = data[i + 1];
  return t1 - t0 > 6 * 3600 ? v0 : v0 + (v1 - v0) * (t - t0) / (t1 - t0);
}
const within = (data, x0, x1) => data.filter(p => p[0] >= x0 && p[0] <= x1).map(p => p[1]);

function heatSpans(D) {
  const all = [...D.heating, ...D.boost].filter(([a, b]) => b > a).sort((p, q) => p[0] - q[0]), out = [];
  for (const [a, b] of all) { const last = out[out.length - 1]; if (last && a - last[1] <= MERGE_GAP) last[1] = Math.max(last[1], b); else out.push([a, b]); }
  return out;
}

class WiserPredictivePanel extends HTMLElement {
  constructor() {
    super();
    this._days = 3; this._entry = null; this._room = null; this._data = null; this._hass = null; this._narrow = false;
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${STYLE}</style><main>
      <div class="bar"><div class="left"><span id="menu"></span><h1 id="title">Predictive Heating</h1></div>
        <div class="ctl"><select id="room" aria-label="Room" hidden></select>
          <div class="btns" role="group" aria-label="Time window"><button data-days="3" aria-pressed="true">3 days</button><button data-days="10" aria-pressed="false">10 days</button></div></div></div>
      <div class="story" id="story"></div>
      <div id="readout">Move over the chart to read the values at that time.</div>
      <div id="chart"></div>
      <p class="note" id="note"></p></main>`;
    this.$ = id => root.getElementById(id);
    root.querySelectorAll('button[data-days]').forEach(b => b.addEventListener('click', () => {
      this._days = +b.dataset.days;
      root.querySelectorAll('button[data-days]').forEach(o => o.setAttribute('aria-pressed', o === b));
      this._load();
    }));
    this.$('room').addEventListener('change', e => { const [entry, room] = e.target.value.split('|'); this._entry = entry; this._room = room; this._load(); });
    new ResizeObserver(() => { clearTimeout(this._rt); this._rt = setTimeout(() => this._data && this._render(), 80); }).observe(this);
  }
  connectedCallback() { this._timer = setInterval(() => this._load(), 5 * 60 * 1000); if (this._hass) this._load(); }  /* the chart is refreshed every 5 min: the 0.1 C sensors and hourly weather change slower than that */
  disconnectedCallback() { clearInterval(this._timer); }
  set hass(h) {
    const first = !this._hass, dark = !!(h.themes && h.themes.darkMode), was = this.hasAttribute('dark');
    this._hass = h; this.toggleAttribute('dark', dark);
    if (first && this.isConnected) this._load(); else if (dark !== was && this._data) this._render();
  }
  set narrow(n) {
    this._narrow = n; const slot = this.$('menu'); slot.textContent = '';
    if (n) { const m = document.createElement('ha-menu-button'); m.hass = this._hass; m.narrow = n; slot.appendChild(m); }
  }
  set panel(_p) {}

  async _load() {
    if (!this._hass) return;
    try {
      const r = await this._hass.callWS({ type: 'wiser_predictive/chart', days: this._days, ...(this._entry ? { entry_id: this._entry } : {}), ...(this._room ? { room: this._room } : {}) });
      this._entry = r.entry_id; this._room = r.room; this._data = r.chart; this._fillRooms(r);
      if (!r.chart) { this.$('chart').innerHTML = '<div class="empty">No rooms are chosen. Add rooms in the Wiser Predictive options.</div>'; this.$('story').innerHTML = ''; return; }
      this._story(); this._render(); this._notes();
    } catch (e) {
      this.$('chart').innerHTML = `<div class="empty">The chart could not be loaded: ${String(e.message || e.code || e).replace(/</g, '&lt;')}</div>`;
    }
  }
  _fillRooms(r) {
    const sel = this.$('room'), options = r.entries.flatMap(e => e.rooms.map(x => ({ v: `${e.entry_id}|${x.entity_id}`, label: r.entries.length > 1 ? `${x.name} (${e.title})` : x.name })));
    sel.hidden = options.length < 2; sel.textContent = '';
    for (const o of options) { const op = document.createElement('option'); op.value = o.v; op.textContent = o.label; sel.appendChild(op); }
    sel.value = `${r.entry_id}|${r.room}`;
  }
  _css(n) { return getComputedStyle(this).getPropertyValue(n).trim(); }

  _story() {
    const D = this._data, x0 = D.now - this._days * 86400, days = this._days;
    this.$('title').textContent = D.name;
    const sum = (data, label, color) => {
      const v = within(data, x0, D.now); if (!v.length) return '';
      const start = at(data, x0, true) ?? v[0], now = v[v.length - 1], lo = Math.min(...v), hi = Math.max(...v), change = now - start;
      return `<div><div class="k"><i style="border-color:var(${color})"></i>${label}</div><div class="v">${num(now)}° now</div>
        <div class="d">${days} days ago ${num(start)}°, lowest ${num(lo)}°, highest ${num(hi)}°. ${Math.abs(change) < .15 ? 'About the same.' : change < 0 ? `Down ${num(-change)}°.` : `Up ${num(change)}°.`}</div></div>`;
    };
    const heats = heatSpans(D).filter(([, b]) => b > x0), mins = Math.round(heats.reduce((s, [a, b]) => s + (Math.min(b, D.now) - Math.max(a, x0)) / 60, 0));
    const when = heats.slice(-3).map(([a]) => fmtT(a, { weekday: 'short', hour: '2-digit', minute: '2-digit' })).join(', ');
    this.$('story').innerHTML = sum(D.reading, 'Inside', '--in') + sum(D.outside, 'Outside', '--out') +
      `<div><div class="k"><i style="border-color:var(--heat-ink)"></i>Heating on</div><div class="v">${heats.length} ${heats.length === 1 ? 'time' : 'times'}, ${mins} min in all</div>
        <div class="d">${heats.length ? `Latest: ${when}.` : 'It did not come on.'}</div></div>`;
  }
  _notes() {
    const D = this._data;
    this.$('note').textContent = (D.notes.length ? D.notes.join(' ') + ' ' : '') +
      `Recorded history up to ${fmtT(D.now, { weekday: 'short', hour: '2-digit', minute: '2-digit' })}. Heating is the room's boost and heating periods from Wiser. The prediction is added to this chart in the next stage.`;
  }

  _render() {
    const D = this._data, root = this.$('chart');
    if (!D.reading.length) { root.innerHTML = '<div class="empty">No readings were recorded for this room in this window.</div>'; return; }
    const W = Math.max(320, root.clientWidth || 800), days = this._days, x0 = D.now - days * 86400, x1 = D.end;
    const X = t => LEFT + (t - x0) / (x1 - x0) * (W - LEFT - RIGHT), css = n => this._css(n);
    const heats = heatSpans(D).filter(([, b]) => b > x0);
    const panels = [
      { id: 'in', h: 260, title: `Inside ${D.name}, °C`, color: '--in', lines: [{ data: D.reading, w: 2.6 }] },
      { id: 'out', h: 170, title: 'Outside, °C', color: '--out', lines: [{ data: D.outside, w: 2.4 }, { data: D.forecast, w: 2.4, dash: '6 4' }] },
    ];
    let y = 4, body = '', first = null;
    for (const p of panels) {
      const vals = p.lines.flatMap(l => visible(l.data, x0, x1).map(q => q[1]));
      if (!vals.length) { continue; }
      let lo = Math.min(...vals), hi = Math.max(...vals); const pad = Math.max((hi - lo) * .12, .4); lo -= pad; hi += pad;
      const top = y + TITLE, bot = top + p.h, Y = v => bot - (v - lo) / (hi - lo) * p.h;
      first = first ?? top;
      body += `<text class="pt" x="${LEFT}" y="${y + 16}">${p.title.replace(/</g, '&lt;')}</text>`;
      for (const v of niceTicks(lo, hi, 4)) body += `<line x1="${LEFT}" x2="${W - RIGHT}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--grid')}"/><text class="mono" x="${LEFT - 8}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(v % 1 ? 1 : 0)}°</text>`;
      const nowX = X(D.now);
      body += `<rect x="${nowX}" y="${top}" width="${Math.max(0, W - RIGHT - nowX)}" height="${p.h}" fill="${css('--fc')}"/>`;
      for (const [a, b] of heats) body += `<rect x="${X(Math.max(a, x0))}" y="${top}" width="${Math.max(2, X(b) - X(Math.max(a, x0)))}" height="${p.h}" fill="${css('--heat')}"/>`;
      body += `<clipPath id="c-${p.id}"><rect x="${LEFT}" y="${top}" width="${W - LEFT - RIGHT}" height="${p.h}"/></clipPath><g clip-path="url(#c-${p.id})">`;
      for (const l of p.lines) {
        const pts = visible(l.data, x0, x1); if (!pts.length) continue;
        body += `<path d="${pts.map(([t, v], i) => (i ? 'L' : 'M') + X(t) + ' ' + Y(v)).join(' ')}" fill="none" stroke="${css(p.color)}" stroke-width="${l.w}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round"/>`;
      }
      body += '</g>';
      if (p.id === 'out' && D.forecast.length) body += `<text x="${X(D.now) + 6}" y="${top + 14}">forecast →</text>`;
      y = bot + GAP;
    }
    const bottom = y - GAP, stepH = (days <= 3 ? 6 : 24) * (W < 600 ? 2 : 1);
    const f = new Date(x0 * 1000); f.setMinutes(0, 0, 0); f.setHours(Math.ceil((f.getHours() + 1) / stepH) * stepH);
    for (let d = f; d.getTime() / 1000 <= x1; d = new Date(d.getTime() + stepH * 3600e3)) {
      const t = d.getTime() / 1000, mid = d.getHours() === 0;
      body += `<line x1="${X(t)}" x2="${X(t)}" y1="${first}" y2="${bottom}" stroke="${css(mid ? '--axis' : '--grid')}" stroke-width="${mid ? 1 : .5}"/>`;
      body += `<text x="${X(t)}" y="${bottom + 16}" text-anchor="middle">${mid ? fmtT(t, { weekday: 'short', day: 'numeric' }) : String(d.getHours()).padStart(2, '0') + ':00'}</text>`;
    }
    let lastLabel = -1e9;  /* label a heat-up only if there is room after the previous label: the text is about 95 px wide */
    if (days <= 3) for (const [a] of heats) if (a >= x0 && X(a) - lastLabel > 100) { body += `<text class="heat" x="${X(a) + 3}" y="${first + 12}">heating ${hhmm(a)}</text>`; lastLabel = X(a); }
    const nowX = X(D.now);
    body += `<line x1="${nowX}" x2="${nowX}" y1="${first}" y2="${bottom}" stroke="${css('--ink')}" stroke-width="1.5"/><text class="pt" x="${nowX}" y="${first - 6}" text-anchor="middle">now</text>`;
    body += `<line id="hv" x1="0" x2="0" y1="${first}" y2="${bottom}" stroke="${css('--ink')}" stroke-dasharray="2 3" visibility="hidden"/>`;
    const H = bottom + AXIS;
    root.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Inside and outside temperature, with the periods the heating was on shaded">${body}</svg>`;
    const svg = root.querySelector('svg'), hv = svg.querySelector('#hv');
    const move = e => {
      const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
      if (px < LEFT || px > W - RIGHT) return;
      const t = x0 + (px - LEFT) / (W - LEFT - RIGHT) * (x1 - x0), future = t > D.now, h = heats.some(([a, b]) => t >= a && t <= b);
      hv.setAttribute('x1', px); hv.setAttribute('x2', px); hv.setAttribute('visibility', 'visible');
      this.$('readout').textContent = future
        ? `${fmtT(t, { weekday: 'short', hour: '2-digit', minute: '2-digit' })} · forecast outside ${num(at(D.forecast, t, false))}°`
        : `${fmtT(t, { weekday: 'short', hour: '2-digit', minute: '2-digit' })} · inside ${num(at(D.reading, t, true))}° · outside ${num(at(D.outside, t, true))}° · heating ${h ? 'ON' : 'off'}`;
    };
    svg.addEventListener('pointermove', move); svg.addEventListener('pointerdown', move);
  }
}

if (!customElements.get('wiser-predictive-panel')) customElements.define('wiser-predictive-panel', WiserPredictivePanel);
