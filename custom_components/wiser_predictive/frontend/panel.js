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
.story{ display:flex; flex-direction:column; gap:14px; }
.group h2{ font-size:13px; font-weight:600; letter-spacing:.02em; text-transform:uppercase; color:var(--muted); margin:0 0 6px; }
.group .gn{ text-transform:none; letter-spacing:0; font-weight:400; margin-left:8px; color:var(--heat-ink); }
.tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }
.tile{ background:var(--panel); border-radius:8px; padding:10px 12px; min-width:0; }
.tile .l{ font-size:12px; color:var(--muted); }
.tile .n{ font-size:22px; font-weight:500; line-height:1.25; font-variant-numeric:tabular-nums; }
.tile .s{ font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
#readout{ background:var(--panel); border-radius:6px; padding:8px 12px; min-height:2.6em; font-family:ui-monospace,"Roboto Mono",monospace; font-size:13px; font-variant-numeric:tabular-nums; }
#chart{ background:var(--panel); border-radius:8px; padding:8px 0; }
svg{ display:block; width:100%; touch-action:pan-y; }
svg text{ fill:var(--muted); font-size:12px; font-family:inherit; }
svg text.pt{ fill:var(--ink); font-weight:600; font-size:14px; }
svg text.heat{ fill:var(--heat-ink); font-weight:600; font-size:11px; }
svg text.mono{ font-family:ui-monospace,"Roboto Mono",monospace; }
.note{ color:var(--muted); font-size:13px; max-width:80ch; margin:0; }
.empty{ padding:28px 16px; color:var(--muted); text-align:center; }
.explain{ background:var(--panel); border-radius:8px; padding:10px 14px; font-size:13px; }
.explain summary{ cursor:pointer; font-weight:600; }
.explain dt{ font-weight:600; margin-top:8px; }
.explain dd{ margin:2px 0 0; color:var(--muted); max-width:80ch; }
.rooms{ background:var(--panel); border-radius:8px; padding:12px 14px; }
.rooms h2{ font-size:15px; font-weight:600; margin:0 0 8px; }
.scroll{ overflow-x:auto; }
table{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th,td{ text-align:left; padding:6px 12px 6px 0; font-size:13px; white-space:nowrap; border-bottom:1px solid var(--grid); }
thead th{ color:var(--muted); font-weight:600; }
tbody th{ font-weight:600; }
tr.me td,tr.me th{ background:rgba(127,140,135,.12); }
.sd{ color:var(--muted); }
`;

const MERGE_GAP = 20 * 60;  /* seconds. Wiser's boost and heating spans are merged when less than 20 min apart: a boost lasts 14-15 min, so one heat-up is one band. */
const LEFT = 46, RIGHT = 12, TITLE = 24, GAP = 14, AXIS = 30;

/* Times are shown in TZ: the house's clock (Home Assistant's time zone) by default, because the heating is at the house and
   its schedules run on that clock, or the viewer's own clock. undefined means the browser's. Set before every draw. */
let TZ;
const fmtT = (t, o) => new Date(t * 1000).toLocaleString([], TZ ? { ...o, timeZone: TZ } : o);
function tzOffset(t) {  /* seconds the clock in TZ is ahead of UTC at time t */
  if (!TZ) return -new Date(t * 1000).getTimezoneOffset() * 60;
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: TZ, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    .formatToParts(new Date(t * 1000)).map(x => [x.type, x.value]));
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) / 1000 - Math.floor(t);
}
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
    this._days = 3; this._cold = 0; this._tzMode = 'server'; this._entry = null; this._room = null; this._data = null; this._hass = null; this._narrow = false;
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${STYLE}</style><main>
      <div class="bar"><div class="left"><span id="menu"></span><h1 id="title">Predictive Heating</h1></div>
        <div class="ctl"><select id="room" aria-label="Room" hidden></select>
          <select id="tz" aria-label="Which clock the times use" title="The house's clock is Home Assistant's time zone"><option value="server">House time</option><option value="browser">My time</option></select>
          <select id="cold" aria-label="What if the weather turns colder" title="Shifts the forecast down to see how the prediction reacts"><option value="0">Forecast as it is</option><option value="3">What if 3° colder</option><option value="5">What if 5° colder</option><option value="8">What if 8° colder</option></select>
          <div class="btns" role="group" aria-label="Time window"><button data-days="3" aria-pressed="true">3 days</button><button data-days="10" aria-pressed="false">10 days</button></div></div></div>
      <div class="story" id="story"></div>
      <div id="readout">Move over the chart to read the values at that time.</div>
      <div id="chart"></div>
      <div id="rooms"></div>
      <details class="explain"><summary>What do these figures mean?</summary>
        <dl><dt>Thermal time constant</dt><dd>The room's thermal capacitance divided by its heat loss coefficient: the time to cover 63% of a change in the outside temperature. A long one means the room changes slowly. The ± is how far the figure moves if any one day is left out, so a wide ± means it is not yet well known; it narrows as days are added.</dd>
        <dt>Outdoor coupling</dt><dd>How many degrees the settled room temperature moves for each degree of outside change. Below 1 means heat is also exchanged with other rooms or gained inside.</dd>
        <dt>Daily swing</dt><dd>How late, and how much smaller, the day-and-night swing of the outside temperature is inside the room (the time lag and decrement of building physics).</dd>
        <dt>Settles at</dt><dd>The temperature the room heads for with no heating, for a steady outside temperature.</dd>
        <dt>Heat response</dt><dd>How the room heats up with heat on: it heads for this maximum with this time constant.</dd>
        <dt>Learned from</dt><dd>Every completed day is kept, so the figures use all of them. Once 14 days are kept, how fast older days fade is chosen by predicting each recent day from the days before it.</dd></dl></details>
      <p class="note" id="note"></p></main>`;
    this.$ = id => root.getElementById(id);
    root.querySelectorAll('button[data-days]').forEach(b => b.addEventListener('click', () => {
      this._days = +b.dataset.days;
      root.querySelectorAll('button[data-days]').forEach(o => o.setAttribute('aria-pressed', o === b));
      this._load();
    }));
    this.$('tz').addEventListener('change', e => { this._tzMode = e.target.value; if (this._data) { this._clock(); this._story(); this._render(); this._notes(); } });
    this.$('cold').addEventListener('change', e => { this._cold = +e.target.value; this._load(); });
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
      const r = await this._hass.callWS({ type: 'wiser_predictive/chart', days: this._days, outside_offset: -this._cold, ...(this._entry ? { entry_id: this._entry } : {}), ...(this._room ? { room: this._room } : {}) });
      this._entry = r.entry_id; this._room = r.room; this._data = r.chart; this._fillRooms(r); this._clock();
      if (!r.chart) { this.$('chart').innerHTML = '<div class="empty">No rooms are chosen. Add rooms in the Wiser Predictive options.</div>'; this.$('story').innerHTML = ''; return; }
      this._story(); this._render(); this._notes();
      if (this._roomsFor !== this._entry) { this._roomsFor = this._entry; this._loadRooms(); }
    } catch (e) {
      this.$('chart').innerHTML = `<div class="empty">The chart could not be loaded: ${String(e.message || e.code || e).replace(/</g, '&lt;')}</div>`;
    }
  }
  async _loadRooms() {  /* what each room is like, learned from its history; asked for once per entry, not on the 5-minute refresh */
    try { this._rooms = await this._hass.callWS({ type: 'wiser_predictive/rooms', ...(this._entry ? { entry_id: this._entry } : {}) }); } catch (e) { this._rooms = null; }
    this._roomsTable();
  }
  _roomsTable() {
    const el = this.$('rooms'), r = this._rooms;
    if (!r || !r.rooms.length) { el.innerHTML = r && r.notes.length ? `<p class="note">${r.notes.join(' ').replace(/</g, '&lt;')}</p>` : ''; return; }
    const pm = (v, s, d) => `${v.toFixed(d)}${s === null || s === undefined ? '' : ` <span class="sd">±${s.toFixed(d)}</span>`}`;
    const rows = r.rooms.map(x => {
      const c = x.character, me = x.entity_id === this._room ? ' class="me"' : '';
      if (!c) return `<tr${me}><th>${x.name.replace(/</g, '&lt;')}</th><td colspan="5" class="sd">not enough free-cooling history yet</td></tr>`;
      return `<tr${me}><th>${x.name.replace(/</g, '&lt;')}</th><td>${pm(c.tau_h, c.tau_se_h, 1)} h</td><td>${pm(c.coupling, c.coupling_se, 2)}</td>
        <td>${c.delay_h.toFixed(1)} h, to ${Math.round(c.damping * 100)}%</td><td>${c.settles[5].toFixed(1)}° / ${c.settles[8].toFixed(1)}° / ${c.settles[11].toFixed(1)}°</td><td>${c.windows}</td></tr>`;
    }).join('');
    el.innerHTML = `<div class="rooms"><h2>What each room is like</h2><div class="scroll"><table><thead><tr><th>Room</th><th>Thermal time constant</th><th>Outdoor coupling</th><th>Daily swing arrives</th><th>Settles at 5° / 8° / 11° outside</th><th>Windows</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note"><b>Thermal time constant (τ)</b> is the room's thermal capacitance divided by its heat loss coefficient: the time to cover 63% of a step change in the outside temperature. <b>Outdoor coupling</b> is how many degrees the settled room temperature moves for each degree of outside change; below 1 means heat is also exchanged with other rooms or gained inside. <b>Daily swing</b> is how late, and how much shrunk, the day-and-night outside swing arrives inside. The <span class="sd">±</span> is how far the figure moves if any one day is left out: differences between rooms smaller than that are not real yet. It narrows as more history is learned from.</p></div>`;
  }
  _fillRooms(r) {
    const sel = this.$('room'), options = r.entries.flatMap(e => e.rooms.map(x => ({ v: `${e.entry_id}|${x.entity_id}`, label: r.entries.length > 1 ? `${x.name} (${e.title})` : x.name })));
    sel.hidden = options.length < 2; sel.textContent = '';
    for (const o of options) { const op = document.createElement('option'); op.value = o.v; op.textContent = o.label; sel.appendChild(op); }
    sel.value = `${r.entry_id}|${r.room}`;
  }
  _css(n) { return getComputedStyle(this).getPropertyValue(n).trim(); }
  _clock() {  /* which time zone every time on the page uses */
    const house = this._hass && this._hass.config && this._hass.config.time_zone;
    TZ = this._tzMode === 'server' && house ? house : undefined;
    this.$('tz').hidden = !house;  /* without a house time zone there is only the browser's clock */
    this._tzName = TZ || Intl.DateTimeFormat().resolvedOptions().timeZone;
  }

  _story() {
    const D = this._data, x0 = D.now - this._days * 86400, days = this._days;
    this.$('title').textContent = D.name;
    /* The header is stat tiles: a label, one number, and (where there is one) its uncertainty or context beneath. Numbers are never
       left inside a sentence. What the terms mean is in the collapsible section below, and on hover. */
    const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const tile = (label, value, sub, help) => `<div class="tile"${help ? ` title="${esc(help)}"` : ''}><div class="l">${esc(label)}</div><div class="n">${value}</div>${sub ? `<div class="s">${sub}</div>` : '<div class="s">&nbsp;</div>'}</div>`;
    const group = (title, tiles, note) => tiles.length ? `<section class="group"><h2>${esc(title)}${note ? ` <span class="gn">${note}</span>` : ''}</h2><div class="tiles">${tiles.join('')}</div></section>` : '';
    const when = t => fmtT(t, { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
    const se = (v, d, unit = '') => (v === null || v === undefined) ? '' : `±${v.toFixed(d)}${unit}`;  /* an uncertainty, shown under its figure */

    /* now */
    const stat = data => {
      const v = within(data, x0, D.now); if (!v.length) return null;
      const start = at(data, x0, true) ?? v[0], now = v[v.length - 1];
      return { now, start, lo: Math.min(...v), hi: Math.max(...v), change: now - start };
    };
    const inn = stat(D.reading), out = stat(D.outside);
    const heats = heatSpans(D).filter(([, b]) => b > x0), mins = Math.round(heats.reduce((s, [a, b]) => s + (Math.min(b, D.now) - Math.max(a, x0)) / 60, 0));
    const change = c => Math.abs(c) < .15 ? 'about the same' : `${c < 0 ? 'down' : 'up'} ${num(Math.abs(c))}° in ${days} days`;
    const nowTiles = [
      ...(inn ? [tile('Inside now', `${num(inn.now)}°`, `${change(inn.change)} · low ${num(inn.lo)}°`)] : []),
      ...(out ? [tile('Outside now', `${num(out.now)}°`, `${change(out.change)} · low ${num(out.lo)}°`)] : []),
      tile(`Heating, last ${days} days`, `${heats.length}×`, `${mins} min in all${heats.length ? ` · last ${when(heats[heats.length - 1][0])}` : ''}`),
    ];

    /* prediction and plan */
    const pr = D.prediction, predTiles = [];
    if (pr) {
      predTiles.push(tile('Minimum', `${num(pr.minimum)}°`, esc(pr.minimum_source), 'The temperature the room must stay above.'));
      predTiles.push(pr.reaches_at
        ? tile('Reaches the minimum', when(pr.reaches_at), 'if nothing heats it', 'When the predicted temperature, with no heating, falls to the minimum.')
        : tile('Stays above the minimum', `to ${when(pr.ends_at)}`, `lowest ${num(pr.lowest[1])}°${pr.falling_at_end ? ' · still falling' : ''}`, `As far as the forecast goes (${Math.round(pr.horizon_h)} h).`));
      if (pr.reaches_at) predTiles.push(tile('Heat needed by', when(pr.call_by), `${Math.round(pr.lead_s / 60)} min before: that is how long heat takes to stop the fall`, 'The latest safe moment to call for heat.'));
      if (pr.outside_low) predTiles.push(tile('Forecast outside low', `${num(pr.outside_low[1])}°`, `at ${when(pr.outside_low[0])}`));
      if (pr.plan && pr.plan.runs.length) {
        const r = pr.plan.runs, a = r[0];
        predTiles.push(tile('Planned heat', `${a.minutes} min`, `from ${when(a.call_by)} · lifts to ${num(a.lifts_to)}°${r.length > 1 ? ` · then ${r.slice(1).map(x => `${x.minutes} min from ${when(x.call_by)}`).join(', ')}` : ''}`,
          'Minutes at full demand, started as late as is safe and just long enough to hold the minimum to the end of the forecast.'));
        predTiles.push(tile('Heat response', `${num(pr.heating.tmax)}° max`, `${Math.round(pr.heating.tau_min)} min time constant · from ${pr.heating.runs} runs`, 'How the room heats up when heat is on: it heads for this temperature with this time constant.'));
      } else if (pr.plan) predTiles.push(tile('Planned heat', 'none', 'stays above the minimum'));
    }
    const predNote = `${this._cold ? `<b>what if ${this._cold}° colder than forecast</b>` : ''}${pr && pr.heating_now ? `${this._cold ? ' · ' : ''}heating is on now: this is what happens if it stops` : ''}`;

    /* the room's thermal character */
    const ch = D.character, info = D.learning, charTiles = [];
    if (ch) {
      charTiles.push(tile('Thermal time constant', `${ch.tau_h.toFixed(1)} h`, se(ch.tau_se_h, 1, ' h'), 'Thermal capacitance divided by heat loss coefficient: the time to cover 63% of a change in the outside temperature.'));
      charTiles.push(tile('Outdoor coupling', ch.coupling.toFixed(2), se(ch.coupling_se, 2), 'Degrees the settled room temperature moves for each degree of outside change. Below 1: heat is also exchanged with other rooms or gained inside.'));
      charTiles.push(tile('Daily swing arrives', `${ch.delay_h.toFixed(1)} h late`, `shrunk to ${Math.round(ch.damping * 100)}%`, 'How late, and how much smaller, the day-and-night outside temperature swing is inside this room (time lag and decrement).'));
      charTiles.push(tile('Settles at 8° outside', `${ch.settles[8].toFixed(1)}°`, `5°: ${ch.settles[5].toFixed(1)}° · 11°: ${ch.settles[11].toFixed(1)}°`, 'The temperature the room heads for with no heating, for a steady outside temperature.'));
      if (info) charTiles.push(tile('Learned from', `${info.days} days`, `${info.windows} windows · ${info.half_life_days ? `older days fade, half-life ${info.half_life_days} d` : info.chosen_by_days ? 'no fading' : 'no fading yet (needs 14 days)'}`, 'Every completed day is kept. ± is how far a figure moves if any one day is left out; it narrows as days are added.'));
    }
    this.$('story').innerHTML = group('Now', nowTiles) + group('Prediction and plan', predTiles, predNote) + group(`${D.name}: thermal character`, charTiles);
  }
  _notes() {
    const D = this._data;
    this.$('note').textContent = (D.notes.length ? D.notes.join(' ') + ' ' : '') +
      `Times are on ${this._tzMode === 'server' && TZ ? "the house's" : 'your'} clock (${this._tzName}). Recorded history up to ${fmtT(D.now, { weekday: 'short', hour: '2-digit', minute: '2-digit' })}. Heating is the room's boost and heating periods from Wiser. The dotted blue line is the predicted temperature if no heat is supplied, from the room's own cooling and the outside forecast. The dashed orange line is the temperature with the planned heating.`;
  }

  _render() {
    const D = this._data, root = this.$('chart');
    if (!D.reading.length) { root.innerHTML = '<div class="empty">No readings were recorded for this room in this window.</div>'; return; }
    const W = Math.max(320, root.clientWidth || 800), days = this._days, x0 = D.now - days * 86400, x1 = D.end;
    const X = t => LEFT + (t - x0) / (x1 - x0) * (W - LEFT - RIGHT), css = n => this._css(n);
    const heats = heatSpans(D).filter(([, b]) => b > x0), pr = D.prediction;
    const panels = [
      { id: 'in', h: 260, title: `Inside ${D.name}, °C`, color: '--in', extra: pr ? [pr.minimum, ...pr.curve.map(c => c[1]), ...(pr.plan ? pr.plan.curve.map(c => c[1]) : [])] : [],
        lines: [{ data: D.reading, w: 2.6 }, ...(pr ? [{ data: pr.curve, w: 2.4, dash: '2 5' }] : []),
          ...(pr && pr.plan && pr.plan.runs.length ? [{ data: pr.plan.curve, w: 2.4, dash: '8 4', color: '--heat-ink' }] : [])] },
      { id: 'out', h: 170, title: 'Outside, °C', color: '--out', lines: [{ data: D.outside, w: 2.4 }, { data: D.forecast, w: 2.4, dash: '6 4' }] },
    ];
    let y = 4, body = '', first = null;
    for (const p of panels) {
      const vals = [...p.lines.flatMap(l => visible(l.data, x0, x1).map(q => q[1])), ...(p.extra || [])];
      if (!vals.length) { continue; }
      let lo = Math.min(...vals), hi = Math.max(...vals); const pad = Math.max((hi - lo) * .12, .4); lo -= pad; hi += pad;
      const top = y + TITLE, bot = top + p.h, Y = v => bot - (v - lo) / (hi - lo) * p.h;
      first = first ?? top;
      body += `<text class="pt" x="${LEFT}" y="${y + 16}">${p.title.replace(/</g, '&lt;')}</text>`;
      for (const v of niceTicks(lo, hi, p.h > 200 ? 6 : 4)) body += `<line x1="${LEFT}" x2="${W - RIGHT}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--grid')}"/><text class="mono" x="${LEFT - 8}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(v % 1 ? 1 : 0)}°</text>`;
      const nowX = X(D.now);
      body += `<rect x="${nowX}" y="${top}" width="${Math.max(0, W - RIGHT - nowX)}" height="${p.h}" fill="${css('--fc')}"/>`;
      for (const [a, b] of heats) body += `<rect x="${X(Math.max(a, x0))}" y="${top}" width="${Math.max(2, X(b) - X(Math.max(a, x0)))}" height="${p.h}" fill="${css('--heat')}"/>`;
      body += `<clipPath id="c-${p.id}"><rect x="${LEFT}" y="${top}" width="${W - LEFT - RIGHT}" height="${p.h}"/></clipPath><g clip-path="url(#c-${p.id})">`;
      for (const l of p.lines) {
        const pts = visible(l.data, x0, x1); if (!pts.length) continue;
        body += `<path d="${pts.map(([t, v], i) => (i ? 'L' : 'M') + X(t) + ' ' + Y(v)).join(' ')}" fill="none" stroke="${css(l.color || p.color)}" stroke-width="${l.w}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round"/>`;
      }
      body += '</g>';
      if (p.id === 'in' && pr) {  /* the room's minimum, and the moment heat must be called if the room is left alone */
        body += `<line x1="${LEFT}" x2="${W - RIGHT}" y1="${Y(pr.minimum)}" y2="${Y(pr.minimum)}" stroke="${css('--heat-ink')}" stroke-width="1.5" stroke-dasharray="7 4"/>`;
        body += `<text x="${LEFT + 6}" y="${Y(pr.minimum) - 5}" class="heat">minimum ${num(pr.minimum)}°</text>`;
        if (pr.call_by && pr.call_by <= x1) {
          const cx = X(pr.call_by);
          body += `<line x1="${cx}" x2="${cx}" y1="${top}" y2="${bot}" stroke="${css('--heat-ink')}" stroke-width="2"/><circle cx="${X(pr.reaches_at)}" cy="${Y(pr.minimum)}" r="5" fill="${css('--heat-ink')}"/>`;
          body += `<text class="heat" x="${cx - 5}" y="${top + 26}" text-anchor="${cx > W - 160 ? 'end' : 'start'}" ${cx > W - 160 ? '' : `dx="10"`}>heat by ${hhmm(pr.call_by)}</text>`;
        }
      }
      if (p.id === 'out' && D.forecast.length) body += `<text x="${X(D.now) + 6}" y="${top + 14}">forecast →</text>`;
      y = bot + GAP;
    }
    const bottom = y - GAP, stepH = (days <= 3 ? 6 : 24) * (W < 600 ? 2 : 1);
    const stepS = stepH * 3600, off0 = tzOffset(x0);  /* ticks every stepH hours on the TZ clock, so midnight lines fall on its midnight */
    for (let t = Math.ceil((x0 + off0) / stepS) * stepS - off0; t <= x1; t += stepS) {
      const hour = (((Math.floor((t + tzOffset(t)) / 3600)) % 24) + 24) % 24, mid = hour === 0;
      body += `<line x1="${X(t)}" x2="${X(t)}" y1="${first}" y2="${bottom}" stroke="${css(mid ? '--axis' : '--grid')}" stroke-width="${mid ? 1 : .5}"/>`;
      body += `<text x="${X(t)}" y="${bottom + 16}" text-anchor="middle">${mid ? fmtT(t, { weekday: 'short', day: 'numeric' }) : String(hour).padStart(2, '0') + ':00'}</text>`;
    }
    let lastLabel = -1e9;  /* label a heat-up only if there is room after the previous label: the text is about 95 px wide */
    if (days <= 3) for (const [a] of heats) if (a >= x0 && X(a) - lastLabel > 100) { body += `<text class="heat" x="${X(a) + 3}" y="${first + 12}">heating ${hhmm(a)}</text>`; lastLabel = X(a); }
    const nowX = X(D.now);
    body += `<line x1="${nowX}" x2="${nowX}" y1="${first}" y2="${bottom}" stroke="${css('--ink')}" stroke-width="1.5"/><text class="pt" x="${nowX}" y="${first - 6}" text-anchor="middle">now</text>`;
    body += `<line id="hv" x1="0" x2="0" y1="${first}" y2="${bottom}" stroke="${css('--ink')}" stroke-dasharray="2 3" visibility="hidden"/>`;
    const H = bottom + AXIS;
    root.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Inside and outside temperature, with the periods the heating was on shaded">${body}</svg>`;
    const svg = root.querySelector('svg'), hv = svg.querySelector('#hv');
    const tip = document.createElementNS('http://www.w3.org/2000/svg', 'g'); tip.setAttribute('visibility', 'hidden'); tip.setAttribute('pointer-events', 'none'); svg.appendChild(tip);
    svg.addEventListener('pointerleave', () => { tip.setAttribute('visibility', 'hidden'); hv.setAttribute('visibility', 'hidden'); });
    const move = e => {
      const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
      if (px < LEFT || px > W - RIGHT) return;
      const t = x0 + (px - LEFT) / (W - LEFT - RIGHT) * (x1 - x0), future = t > D.now, h = heats.some(([a, b]) => t >= a && t <= b);
      hv.setAttribute('x1', px); hv.setAttribute('x2', px); hv.setAttribute('visibility', 'visible');
      const when = fmtT(t, { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
      const lines = future
        ? [...(pr ? [`Predicted inside ${num(at(pr.curve, t, false))}°`] : []), ...(pr && pr.plan && pr.plan.runs.length ? [`With the plan ${num(at(pr.plan.curve, t, false))}°`] : []), `Outside forecast ${num(at(D.forecast, t, false))}°`]
        : [`Inside ${num(at(D.reading, t, true))}°`, `Outside ${num(at(D.outside, t, true))}°`, ...(h ? ['Heating on'] : [])];
      this.$('readout').textContent = `${when} · ${lines.join(' · ')}`;
      /* a label beside the cursor: the time and the values at that time */
      const rows = [when, ...lines], w = Math.max(...rows.map(s => s.length)) * 7.4 + 18, hh = rows.length * 16 + 8;
      const yy = Math.min(Math.max(4, (e.clientY - r.top) * (H / r.height) - hh / 2), H - hh - 4), xx = px + 14 + w > W - RIGHT ? px - 14 - w : px + 14;
      tip.setAttribute('visibility', 'visible');
      tip.innerHTML = `<rect x="${xx}" y="${yy}" width="${w}" height="${hh}" rx="5" fill="${css('--panel')}" stroke="${css('--axis')}"/>` +
        rows.map((s, i) => `<text x="${xx + 8}" y="${yy + 17 + i * 16}" class="${i ? '' : 'pt'}" style="font-size:12px">${s}</text>`).join('');
    };
    svg.addEventListener('pointermove', move); svg.addEventListener('pointerdown', move);
  }
}

if (!customElements.get('wiser-predictive-panel')) customElements.define('wiser-predictive-panel', WiserPredictivePanel);
