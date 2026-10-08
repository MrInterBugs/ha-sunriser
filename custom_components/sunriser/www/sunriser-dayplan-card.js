// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
//
// SunRiser Day Planner Card
//
// Optional config:
//   title: "My Aquarium"          # card title (default: "Day Planner")
//   refresh_interval: 300         # seconds between refreshes (default: 300)
//   device_id: "..."              # required with multiple loaded controllers
//   channels:                     # override labels per PWM
//     1: "4500K White"
//     2: "Royal Blue"

import { LitElement, html, css } from "https://unpkg.com/lit@3/index.js?module";
import { unsafeSVG } from "https://unpkg.com/lit@3/directives/unsafe-svg.js?module";

// LED colour map — sourced from sunriser_colors_config.js, matching the colours
// used by the firmware's own dayplanner UI.  Very pale colours (e.g. 6500K sky
// white) are intentionally kept as-is so the chart matches the device UI; they
// show well on dark HA themes.  The FALLBACK_PALETTE is used for unrecognised
// color_ids or when color_id is empty.
const LED_COLORS = {
  "625nm":      "#ff5700",
  "3500k":      "#ffc987",
  "4500k":      "#ffdf88",
  "5500k":      "#ffeede",
  "6500k":      "#fff9fb",
  "7500k":      "#eeefff",
  "coralmix":   "#dddfff",
  "11000k":     "#c3d6ff",
  "13000k":     "#beceff",
  "465nm":      "#66a3ff",
  "growx5":     "#ff66cc",
  "pump":       "#ababab",
  "co":         "#33cc33",
  "custom":     "#ffff00",
  "custompink": "#ff00ff",
  "customcyan": "#00ffff",
  "customblue": "#0000ff",
  "customred":  "#ff0000",
  "powermain":  "#ffeede",
  "powermoon":  "#beceff",
  "powersunrise":"#ffc987",
  "spotmain":   "#ffeede",
  "spotmoon":   "#beceff",
  "spotsunrise":"#ffc987",
};

const FALLBACK_PALETTE = [
  "#66a3ff", "#ffdf88", "#ff66cc", "#33cc33",
  "#ffc987", "#c3d6ff", "#ff5700", "#ababab",
  "#a0d8a0", "#ffaaee",
];

function channelColor(colorId, fallbackIdx) {
  return LED_COLORS[colorId] ?? FALLBACK_PALETTE[fallbackIdx % FALLBACK_PALETTE.length];
}

// ── SVG layout constants ──────────────────────────────────────────────────────
// X axis: 0–1440 SVG units = 0–24h (1 unit per minute)
// Y axis: 0–100 SVG units = 100%–0% (inverted: top of chart = full brightness)
const SVG_W = 1440;
const SVG_H = 100;
// ViewBox matches the data range exactly so 100% touches the top edge.
// overflow:visible in CSS lets marker circles bleed slightly outside without
// the fill area being pushed away from the border.
const VBOX = `-1 0 ${SVG_W + 2} ${SVG_H}`;

function timeToMin(timeStr) {
  const [h, m] = timeStr.split(":").map(Number);
  return h * 60 + m;
}

// Build the SVG <path> data for one channel.
// Returns { fillD, lineD, markerPts } where markerPts are the actual marker
// positions (not the pre/post day-boundary extensions).
function buildChannelPath(markers) {
  const pts = markers
    .map((m) => [timeToMin(m.time), m.percent])
    .sort((a, b) => a[0] - b[0]);

  if (pts.length === 0) return null;

  // The device extends: before the first marker the value equals the last
  // marker's value; after the last marker it equals the first marker's value.
  const extended = [
    [0, pts[pts.length - 1][1]],
    ...pts,
    [SVG_W, pts[0][1]],
  ];

  // SVG coords: x = daymin, y = SVG_H - percent
  const coords = extended.map(([x, p]) => `${x},${SVG_H - p}`);

  const lineD = `M ${coords.join(" L ")}`;
  const fillD = `M 0,${SVG_H} L ${coords.join(" L ")} L ${SVG_W},${SVG_H} Z`;

  return { fillD, lineD, markerPts: pts };
}

function buildSVGContent(schedules) {
  const parts = [];

  // ── Grid ──────────────────────────────────────────────────────────────────
  // Use style attribute so CSS variables resolve inside the shadow DOM.
  const gridStyle =
    'style="stroke: var(--divider-color, #CCD7E2)" stroke-width="0.5" stroke-dasharray="2,2"';
  // Vertical lines at 6 h, 12 h, 18 h
  for (const x of [360, 720, 1080]) {
    parts.push(
      `<line x1="${x}" y1="0" x2="${x}" y2="${SVG_H}" ${gridStyle}/>`
    );
  }
  // Horizontal lines at 25 %, 50 %, 75 %
  for (const p of [25, 50, 75]) {
    const y = SVG_H - p;
    parts.push(
      `<line x1="0" y1="${y}" x2="${SVG_W}" y2="${y}" ${gridStyle}/>`
    );
  }

  // ── Per-channel paths then dots (dots on top) ─────────────────────────────
  const dotLayers = [];
  schedules.forEach(({ markers, color_id }, idx) => {
    const color = channelColor(color_id, idx);
    const built = buildChannelPath(markers);
    if (!built) return;
    const { fillD, lineD, markerPts } = built;

    parts.push(
      `<path d="${fillD}" fill="${color}" fill-opacity="0.22" stroke="none"/>`
    );
    parts.push(
      `<path d="${lineD}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/>`
    );

    // Collect dots for this channel (rendered after all fills+lines)
    markerPts.forEach(([x, p]) => {
      dotLayers.push(
        `<circle cx="${x}" cy="${SVG_H - p}" r="3.5"` +
          ` fill="${color}" stroke="var(--card-background-color,#fff)"` +
          ` stroke-width="1.2"/>`
      );
    });
  });

  // Dots sit above all fill/line layers
  parts.push(...dotLayers);

  return parts.join("\n");
}

// ── Custom element ────────────────────────────────────────────────────────────

class SunRiserDayplanCard extends LitElement {
  static properties = {
    _schedules: { state: true },
    _loading:   { state: true },
    _error:     { state: true },
    _draft: { state: true },
    _saving: { state: true },
    _editError: { state: true },
  };

  static styles = css`
    :host { display: block; }

    ha-card { padding: 0 16px 12px; }
    .channel { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 10px 0; border-top: 1px solid var(--divider-color, #ccc); }
    .channel span { flex: 1 1 180px; }
    .editor { border-top: 1px solid var(--divider-color, #ccc); margin-top: 12px; }
    fieldset { border: 0; padding: 0; min-width: 0; }
    label { display: flex; gap: 12px; justify-content: space-between; margin: 8px 0; }
    table { width: 100%; text-align: left; }
    input { width: 90px; box-sizing: border-box; }
    button, input, select { font: inherit; color: var(--primary-text-color, #222); background: var(--card-background-color, white); border: 1px solid var(--divider-color, #888); border-radius: 4px; padding: 8px; }
    button { cursor: pointer; margin: 4px 4px 4px 0; }
    button:disabled { opacity: .5; cursor: default; }
    [role="alert"] { color: var(--error-color, #b00020); }
    details { padding: 10px 0; }


    .chart-row {
      display: flex;
      align-items: stretch;
      gap: 4px;
    }

    /* Y-axis percentage labels */
    .yaxis {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      align-items: flex-end;
      width: 34px;
      font-size: 0.7em;
      color: var(--secondary-text-color);
      /* bottom padding aligns with x-axis label row */
      padding-bottom: 20px;
      flex-shrink: 0;
      user-select: none;
    }

    /* SVG + x-axis together */
    .chart-col { flex: 1; min-width: 0; }

    svg {
      display: block;
      width: 100%;
      height: 180px;
      background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color, #CCD7E2);
      border-radius: 4px;
      overflow: visible;
    }

    .xaxis {
      display: flex;
      justify-content: space-between;
      font-size: 0.7em;
      color: var(--secondary-text-color);
      margin-top: 3px;
      padding: 0 1px;
      user-select: none;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 14px;
      margin-top: 10px;
      padding-left: 38px;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 0.78em;
      color: var(--primary-text-color);
    }
    .swatch {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .state {
      color: var(--secondary-text-color);
      font-size: 0.9em;
      text-align: center;
      padding: 28px 0;
    }

    .state.error {
      color: var(--error-color, #db4437);
    }

    .state.error code {
      display: inline-block;
      margin-top: 6px;
      font-size: 0.85em;
      color: var(--primary-text-color);
      background: var(--code-editor-background-color, rgba(0,0,0,0.06));
      padding: 2px 6px;
      border-radius: 4px;
    }
  `;

  constructor() {
    super();
    this._schedules = null;
    this._loading = false;
    this._error = null;
    this._initialized = false;
    this._refreshTimer = null;
    this._fetchId = 0;
    this._draft = null;
    this._programs = [];
    this._saving = false;
    this._editError = null;
  }

  setConfig(config) {
    this._config = { ...config };
    this._draft = null;
    this._saving = false;
    this._editError = null;
    this._fetchId++;
    this._loading = false;
    this._schedules = null;
    this._error = null;
    this._initialized = false;
    this.requestUpdate();
    if (this.isConnected) this._startRefreshTimer();
    if (this._hass) {
      this._initialized = true;
      this._fetch();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._fetch();
    }
  }

  connectedCallback() {
    super.connectedCallback();
    this._startRefreshTimer();
    if (this._hass && !this._initialized) {
      this._initialized = true;
      this._fetch();
    }
  }

  _startRefreshTimer() {
    clearInterval(this._refreshTimer);
    const seconds = Number(this._config?.refresh_interval ?? 300);
    const interval = Number.isFinite(seconds) && seconds >= 1 ? seconds : 300;
    this._refreshTimer = setInterval(() => this._fetch(), interval * 1000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._refreshTimer);
    this._refreshTimer = null;
    this._fetchId++;
    this._loading = false;
    this._initialized = false;
    this._draft = null;
    this._saving = false;
  }

  async _fetch() {
    if (!this._hass || this._loading) return;
    const fetchId = ++this._fetchId;
    const hass = this._hass;
    const deviceId = this._config?.device_id;
    this._loading = true;
    this._error = null;

    try {
      const result = await hass.connection.sendMessagePromise({
        type: "call_service", domain: "sunriser", service: "get_planning",
        service_data: deviceId ? { device_id: deviceId } : {}, return_response: true,
      });
      if (fetchId !== this._fetchId) return;
      this._schedules = result.response.channels;
      this._programs = result.response.programs;
      this._weekday = result.response.weekday;
    } catch (err) {
      if (fetchId !== this._fetchId) return;
      this._error = err?.message ?? String(err);
    }
    if (fetchId === this._fetchId) this._loading = false;
  }

  _edit(kind, item) {
    if (this._draft || this._saving) return;
    this._editError = null;
    this._draft = {
      kind, target: kind === "program" ? item.id : item.pwm, name: item.name,
      revision: kind === "program" ? item.revision : item[`${kind}_revision`],
      markers: (kind === "daily" ? item.daily : item.markers || []).map(m => ({ ...m })),
      schedule: [...(item.week || [])], channels: item.channels || [],
    };
  }

  _marker(index, key, value) {
    const markers = this._draft.markers.map((m, i) => i === index ? { ...m, [key]: value } : m);
    this._draft = { ...this._draft, markers };
  }

  _draftProblem() {
    if (!this._draft || this._draft.kind === "week") return null;
    const seen = new Set();
    if (!this._draft.markers.length) return "Add at least one marker.";
    for (const marker of this._draft.markers) {
      if (!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$|^24:00$/.test(marker.time) ||
          !Number.isInteger(marker.percent) || marker.percent < 0 || marker.percent > 100) {
        return "Use times from 00:00 to 24:00 and whole percentages from 0 to 100.";
      }
      if (seen.has(marker.time)) return "Each marker needs a different time.";
      seen.add(marker.time);
    }
    return null;
  }

  async _save() {
    if (!this._draft || this._saving || this._draftProblem()) return;
    const draft = this._draft;
    const deviceId = this._config?.device_id;
    this._saving = true;
    this._editError = null;
    try {
      await this._hass.connection.sendMessagePromise({
        type: "call_service", domain: "sunriser", service: "save_planning",
        service_data: { kind: draft.kind, target: draft.target, revision: draft.revision,
          ...(deviceId ? { device_id: deviceId } : {}),
          ...(draft.kind === "week" ? { schedule: draft.schedule } : { markers: draft.markers }),
        },
      });
      if (this._draft !== draft) return;
      this._draft = null;
      this._fetchId++;
      this._loading = false;
      await this._fetch();
    } catch (err) {
      if (this._draft !== draft) return;
      this._editError = err?.message ?? String(err);
    } finally {
      if (this._draft === draft || this._draft === null) this._saving = false;
    }
  }

  _discard() {
    if (this._saving) return;
    this._draft = null;
    this._editError = null;
    this._schedules = null;
    this._fetchId++;
    this._loading = false;
    return this._fetch();
  }

  _renderEditor() {
    const draft = this._draft;
    if (!draft) return "";
    const problem = this._draftProblem();
    const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Fallback"];
    return html`<section class="editor" aria-label="Schedule editor">
      <h3>${draft.name} — ${draft.kind === "week" ? "Weekly assignments" : "Curve"}</h3>
      ${draft.kind === "program" ? html`<p>This is a shared program. Used by: ${draft.channels.join(", ") || "no channels"}.</p>` : ""}
      ${draft.kind === "daily" ? html`<p>Saving this curve does not change the channel's selected planner.</p>` : ""}
      <fieldset ?disabled=${this._saving}>
      ${draft.kind === "week" ? days.map((day, index) => html`<label>${day}
        <select aria-label=${day} @change=${e => { const schedule = [...draft.schedule]; schedule[index] = Number(e.target.value); this._draft = { ...draft, schedule }; }}>
          <option value="0" ?selected=${draft.schedule[index] === 0}>${index === 7 ? "None" : "Use fallback"}</option>
          ${this._programs.map(p => html`<option value=${p.id} ?selected=${draft.schedule[index] === p.id}>${p.name} [${p.id}]</option>`)}
          ${draft.schedule[index] && !this._programs.some(p => p.id === draft.schedule[index]) ? html`<option selected value=${draft.schedule[index]}>Missing program [${draft.schedule[index]}]</option>` : ""}
        </select></label>`) : html`
        <table><thead><tr><th>Time</th><th>Percent</th><th></th></tr></thead><tbody>
        ${draft.markers.map((marker, index) => html`<tr>
          <td><input aria-label=${`Time ${index + 1}`} .value=${marker.time} @change=${e => this._marker(index, "time", e.target.value)} placeholder="HH:MM" maxlength="5"></td>
          <td><input aria-label=${`Percent ${index + 1}`} type="number" min="0" max="100" step="1" .value=${String(marker.percent ?? "")} @change=${e => this._marker(index, "percent", e.target.value === "" ? null : Number(e.target.value))}></td>
          <td><button @click=${() => { this._draft = { ...draft, markers: draft.markers.filter((_, i) => i !== index) }; }}>Remove</button></td>
        </tr>`)}</tbody></table>
        <button @click=${() => { this._draft = { ...draft, markers: [...draft.markers, { time: "12:00", percent: 0 }] }; }}>Add marker</button>
        ${!problem ? html`<p>Preview — scheduled output, before weather and other overrides</p><svg aria-label="Draft preview" viewBox=${VBOX} preserveAspectRatio="none">${unsafeSVG(buildSVGContent([{ markers: draft.markers }]))}</svg>` : ""}
      `}
      </fieldset>
      ${problem ? html`<p role="alert">${problem}</p>` : ""}
      ${this._editError ? html`<p role="alert">${this._editError} Your draft is kept. Discard and reopen to load current values.</p>` : ""}
      <button ?disabled=${this._saving || !!problem} @click=${() => this._save()}>${this._saving ? "Saving…" : "Save"}</button>
      <button ?disabled=${this._saving} @click=${() => this._discard()}>Discard</button>
    </section>`;
  }

  _renderBody() {
    if (this._loading && !this._schedules) {
      return html`<div class="state">Loading schedules…</div>`;
    }
    if (this._error) {
      return html`
        <div class="state error">
          <b>Could not load schedules</b><br>
          <code>${this._error}</code><br>
          <small>Check the controller connection and the selected SunRiser device.</small>
        </div>`;
    }
    if (!this._schedules || this._schedules.length === 0) {
      return html`<div class="state">No configured channels found.</div>`;
    }

    const legend = this._schedules.map(({ pwm, name, color_id }, idx) => {
      const color = channelColor(color_id, idx);
      const label = this._config?.channels?.[pwm] ?? name;
      return html`
        <span class="legend-item">
          <span class="swatch" style="background:${color}"></span>
          <span>${label}</span>
        </span>`;
    });

    return html`
      <div class="chart-row">
        <div class="yaxis">
          <span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span>
        </div>
        <div class="chart-col">
          <svg viewBox="${VBOX}" preserveAspectRatio="none"
               xmlns="http://www.w3.org/2000/svg">
            ${unsafeSVG(buildSVGContent(this._schedules.filter(s => s.markers.length)))}
          </svg>
          <div class="xaxis">
            <span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span>
          </div>
        </div>
      </div>
      <div class="legend">${legend}</div>
      <p>Scheduled curves before weather, maintenance, or manual overrides.</p>
      ${this._schedules.map(channel => html`<div class="channel">
        <b>${this._config?.channels?.[channel.pwm] ?? channel.name}</b>
        <span>${channel.manager === 1 ? "Daily planner" : channel.manager === 2 ? (this._weekday === null ? "Weekly planner — controller timezone unavailable" : `Weekly planner — ${channel.program_name || "no available program today"}`) : channel.manager === 3 ? `Fixed output: ${channel.fixed / 10}%` : "No planner"}</span>
        <button ?disabled=${!!this._draft} @click=${() => this._edit("daily", channel)}>Edit daily curve</button>
        <button ?disabled=${!!this._draft} @click=${() => this._edit("week", channel)}>Edit week</button>
      </div>`)}
      ${this._programs.length ? html`<details><summary>Named programs</summary>
        ${this._programs.map(program => html`<div class="channel"><span>${program.name} [${program.id}]</span>
          <button ?disabled=${!!this._draft} @click=${() => this._edit("program", program)}>Edit program</button></div>`)}
      </details>` : ""}
      `;
  }

  render() {
    const title = this._config?.title ?? "Day Planner";
    return html`
      <ha-card .header=${title}>
        ${this._renderBody()}
        ${this._renderEditor()}
      </ha-card>`;
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return { title: "Day Planner" };
  }
}

customElements.define("sunriser-dayplan-card", SunRiserDayplanCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "sunriser-dayplan-card",
  name: "SunRiser Day Planner",
  description: "Daily and weekly schedules with explicit save/discard editing",
  preview: true,
  documentationURL: "https://github.com/MrInterBugs/ha-sunriser",
});

// Notify HA that a new custom card type is available (handles the case where
// the module loads after the picker has already been initialised).
window.dispatchEvent(new Event("ll-custom-cards-updated"));
