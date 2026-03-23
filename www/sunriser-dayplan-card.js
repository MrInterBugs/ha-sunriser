// SPDX-License-Identifier: GPL-3.0-or-later
//
// SunRiser Day Planner Card
//
// Installation:
//   1. Copy this file to <ha-config>/www/sunriser-dayplan-card.js
//   2. Add resource in HA: Settings → Dashboards → Resources
//      URL: /local/sunriser-dayplan-card.js  Type: JavaScript module
//   3. Add card to a dashboard:
//        type: custom:sunriser-dayplan-card
//
// Optional config:
//   title: "My Aquarium"          # card title (default: "Day Planner")
//   refresh_interval: 300         # seconds between refreshes (default: 300)
//   channels:                     # override labels per PWM
//     1: "4500K White"
//     2: "Royal Blue"

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
  const gridStyle =
    'stroke="#CCD7E2" stroke-width="0.5" stroke-dasharray="2,2"';
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

  // Border rect
  parts.push(
    `<rect x="0" y="0" width="${SVG_W}" height="${SVG_H}"` +
      ` fill="none" stroke="#CCD7E2" stroke-width="1"/>`
  );

  return parts.join("\n");
}

// ── Custom element ────────────────────────────────────────────────────────────

class SunRiserDayplanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._schedules = null;
    this._loading = false;
    this._initialized = false;
    this._refreshTimer = null;
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._fetch();
    }
  }

  connectedCallback() {
    const interval = (this._config?.refresh_interval ?? 300) * 1000;
    this._refreshTimer = setInterval(() => this._fetch(), interval);
  }

  disconnectedCallback() {
    clearInterval(this._refreshTimer);
    this._refreshTimer = null;
  }

  async _fetch() {
    if (!this._hass) return;
    this._loading = true;
    this._error = null;
    this._render();

    const schedules = [];
    let firstError = null;

    for (let i = 1; i <= 10; i++) {
      try {
        const result = await this._hass.connection.sendMessagePromise({
          type: "call_service",
          domain: "sunriser",
          service: "get_dayplanner_schedule",
          service_data: { pwm: i },
          return_response: true,
        });
        const resp = result?.response;
        const markers = resp?.markers;
        if (markers && markers.length > 0) {
          schedules.push({
            pwm: i,
            name: resp.name ?? `PWM ${i}`,
            color_id: resp.color_id ?? "",
            markers,
          });
        }
      } catch (err) {
        if (!firstError) firstError = err;
        console.error(`[sunriser-dayplan-card] PWM ${i} failed:`, err);
      }
    }

    // If every channel failed, surface the first error rather than showing
    // an empty chart — makes misconfiguration much easier to diagnose.
    if (schedules.length === 0 && firstError) {
      this._error = firstError?.message ?? String(firstError);
    }

    this._schedules = schedules;
    this._loading = false;
    this._render();
  }

  _render() {
    const title = this._config?.title ?? "Day Planner";

    let body;
    if (this._loading && !this._schedules) {
      body = `<div class="state">Loading schedules…</div>`;
    } else if (this._error) {
      body = `<div class="state error">
        <b>Could not load schedules</b><br>
        <code>${this._error}</code><br>
        <small>Check browser console (F12) for details. Make sure the SunRiser
        integration is added in Settings → Integrations.</small>
      </div>`;
    } else if (!this._schedules || this._schedules.length === 0) {
      body = `<div class="state">No day planner schedules found.</div>`;
    } else {
      const svgContent = buildSVGContent(this._schedules);

      const yLabels = ["100%", "75%", "50%", "25%", "0%"]
        .map((l) => `<span>${l}</span>`)
        .join("");

      const legend = this._schedules
        .map(({ pwm, name, color_id }, idx) => {
          const color = channelColor(color_id, idx);
          const label = this._config?.channels?.[pwm] ?? name;
          return (
            `<span class="legend-item">` +
            `<span class="swatch" style="background:${color}"></span>` +
            `<span>${label}</span>` +
            `</span>`
          );
        })
        .join("");

      body = `
        <div class="chart-row">
          <div class="yaxis">${yLabels}</div>
          <div class="chart-col">
            <svg viewBox="${VBOX}" preserveAspectRatio="none"
                 xmlns="http://www.w3.org/2000/svg">
              ${svgContent}
            </svg>
            <div class="xaxis">
              <span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span>
            </div>
          </div>
        </div>
        <div class="legend">${legend}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }

        ha-card { padding: 16px 16px 12px; }

        .title {
          font-size: 1.05em;
          font-weight: 500;
          color: var(--primary-text-color);
          margin-bottom: 12px;
        }

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
          border: 1px solid #CCD7E2;
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
      </style>
      <ha-card>
        <div class="title">${title}</div>
        ${body}
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
  description: "Day planner schedule chart for all active PWM channels",
});
