const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel,
  BorderStyle, WidthType, ShadingType, VerticalAlign, PageNumber,
  TabStopType, TabStopPosition,
} = require("docx");

const dataPath   = process.argv[2];
const outputPath = process.argv[3];

const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

const PAGE_WIDTH    = 12240;
const PAGE_HEIGHT   = 15840;
const MARGIN        = 1440;
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN * 2; // 9360

const NAVY   = "1B2A4A";
const TEAL   = "0E7C7B";
const GREEN  = "1A7F37";
const RED    = "B42318";
const AMBER  = "B54708";
const GREY   = "6B7280";
const LIGHT  = "F3F4F6";
const BORDER_COLOR = "D0D5DD";

const border = { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR };
const cellBorders = { top: border, bottom: border, left: border, right: border };

function fmtDate(iso) {
  if (!iso) return "N/A";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    year: "numeric", month: "long", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function headerCell(text, width) {
  return new TableCell({
    borders: cellBorders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: NAVY, type: ShadingType.CLEAR },
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 18 })],
    })],
  });
}

function bodyCell(text, width, opts = {}) {
  return new TableCell({
    borders: cellBorders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: opts.fill || "FFFFFF", type: ShadingType.CLEAR },
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({
        text: String(text), size: 18,
        color: opts.color || "1F2937", bold: opts.bold || false,
      })],
    })],
  });
}

function statCard(label, value, color) {
  const w = Math.floor(CONTENT_WIDTH / 4);
  return new TableCell({
    borders: cellBorders,
    width: { size: w, type: WidthType.DXA },
    shading: { fill: LIGHT, type: ShadingType.CLEAR },
    margins: { top: 180, bottom: 180, left: 140, right: 140 },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 60 },
        children: [new TextRun({ text: String(value), bold: true, size: 32, color })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: label, size: 16, color: GREY })],
      }),
    ],
  });
}

// ── 1. Executive Summary Cards ──────────────────────────────────────────
const cardWidth = Math.floor(CONTENT_WIDTH / 4);
const statsTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [cardWidth, cardWidth, cardWidth, cardWidth],
  rows: [
    new TableRow({
      children: [
        statCard("Bots Configured", data.total_bots, NAVY),
        statCard("Peak Concurrent", data.config?.concurrency || data.total_bots, TEAL),
        statCard("Test Duration", data.duration_str, NAVY),
        statCard("WebRTC Enabled", data.config?.webrtc_enabled ? "Yes" : "No", GREEN),
      ],
    }),
  ],
});

// ── 2. Table 1: Browser Distribution & Success Rates ──────────────────────
const bList = ["chrome", "safari", "firefox", "edge", "brave", "chrome_mobile", "safari_mobile", "samsung"];
const bNames = {
  "chrome": "Chrome", "safari": "Safari", "firefox": "Firefox", "edge": "Edge", "brave": "Brave",
  "chrome_mobile": "Chrome Mobile", "safari_mobile": "Safari Mobile", "samsung": "Samsung"
};

const t1Cols = [2000, 900, 900, 900, 900, 900, 900, 1000, 1060]; // sum = 9360 (CONTENT_WIDTH)

const browserDistRows = bList.map((b, i) => {
  const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
  const isMobile = b.includes("mobile") || b === "samsung";
  
  // Distribute based on device types
  const dCount = !isMobile ? (data.browser_distribution?.[b] || 0) : 0;
  const mCount = isMobile ? (data.browser_distribution?.[b] || 0) : 0;
  const tabCount = 0; // simulated tablet subset
  const total = dCount + mCount + tabCount;
  
  const joinPerf = data.join_performance?.[b] || { joined: 0, failed: 0, success_rate: 0.0, avg_join_time: 0.0 };
  
  return new TableRow({
    children: [
      bodyCell(bNames[b], t1Cols[0], { fill, bold: true, color: NAVY }),
      bodyCell(dCount, t1Cols[1], { fill, align: AlignmentType.CENTER }),
      bodyCell(mCount, t1Cols[2], { fill, align: AlignmentType.CENTER }),
      bodyCell(tabCount, t1Cols[3], { fill, align: AlignmentType.CENTER }),
      bodyCell(total, t1Cols[4], { fill, align: AlignmentType.CENTER, bold: true }),
      bodyCell(joinPerf.joined || 0, t1Cols[5], { fill, align: AlignmentType.CENTER }),
      bodyCell(joinPerf.failed || 0, t1Cols[6], { fill, align: AlignmentType.CENTER, color: joinPerf.failed > 0 ? RED : "1F2937" }),
      bodyCell(`${(joinPerf.success_rate || 0.0).toFixed(1)}%`, t1Cols[7], { fill, align: AlignmentType.CENTER, color: joinPerf.success_rate >= 90 ? GREEN : AMBER }),
      bodyCell(`${(joinPerf.avg_join_time || 0.0).toFixed(0)} ms`, t1Cols[8], { fill, align: AlignmentType.CENTER })
    ]
  });
});

// Calculate TOTALS row
const dTotal = bList.reduce((acc, b) => acc + (!b.includes("mobile") && b !== "samsung" ? (data.browser_distribution?.[b] || 0) : 0), 0);
const mTotal = bList.reduce((acc, b) => acc + (b.includes("mobile") || b === "samsung" ? (data.browser_distribution?.[b] || 0) : 0), 0);
const totalBotsJoined = Object.values(data.join_performance || {}).reduce((acc, curr) => acc + (curr.joined || 0), 0);
const totalBotsFailed = Object.values(data.join_performance || {}).reduce((acc, curr) => acc + (curr.failed || 0), 0);
const grandTotalBots = totalBotsJoined + totalBotsFailed;
const totalSuccessRate = grandTotalBots > 0 ? (totalBotsJoined / grandTotalBots * 100) : 0;
const totalAvgJoinTime = Object.values(data.join_performance || {}).reduce((acc, curr) => acc + (curr.avg_join_time || 0), 0) / (Object.keys(data.join_performance || {}).length || 1);

const totalsRow = new TableRow({
  children: [
    bodyCell("TOTAL", t1Cols[0], { fill: LIGHT, bold: true, color: NAVY }),
    bodyCell(dTotal, t1Cols[1], { fill: LIGHT, align: AlignmentType.CENTER, bold: true }),
    bodyCell(mTotal, t1Cols[2], { fill: LIGHT, align: AlignmentType.CENTER, bold: true }),
    bodyCell(0, t1Cols[3], { fill: LIGHT, align: AlignmentType.CENTER, bold: true }),
    bodyCell(grandTotalBots, t1Cols[4], { fill: LIGHT, align: AlignmentType.CENTER, bold: true }),
    bodyCell(totalBotsJoined, t1Cols[5], { fill: LIGHT, align: AlignmentType.CENTER, bold: true }),
    bodyCell(totalBotsFailed, t1Cols[6], { fill: LIGHT, align: AlignmentType.CENTER, bold: true, color: totalBotsFailed > 0 ? RED : "1F2937" }),
    bodyCell(`${totalSuccessRate.toFixed(1)}%`, t1Cols[7], { fill: LIGHT, align: AlignmentType.CENTER, bold: true, color: totalSuccessRate >= 90 ? GREEN : AMBER }),
    bodyCell(`${totalAvgJoinTime.toFixed(0)} ms`, t1Cols[8], { fill: LIGHT, align: AlignmentType.CENTER, bold: true })
  ]
});

const t1Table = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: t1Cols,
  rows: [
    new TableRow({
      children: [
        headerCell("Browser", t1Cols[0]),
        headerCell("Desktop", t1Cols[1]),
        headerCell("Mobile", t1Cols[2]),
        headerCell("Tablet", t1Cols[3]),
        headerCell("Total", t1Cols[4]),
        headerCell("Joined", t1Cols[5]),
        headerCell("Failed", t1Cols[6]),
        headerCell("Success %", t1Cols[7]),
        headerCell("Avg Join Time", t1Cols[8])
      ]
    }),
    ...browserDistRows,
    totalsRow
  ]
});

// ── 3. Table 2: WebRTC Performance by Browser ────────────────────────────
const t2Cols = [1500, 900, 900, 900, 900, 900, 1000, 1100, 1260]; // sum = 9360
const webrtcBrowsers = ["chrome", "safari", "firefox", "edge", "chrome_mobile", "safari_mobile"];

const webrtcRows = webrtcBrowsers.map((b, i) => {
  const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
  const p = data.webrtc_performance?.[b] || {
    avg_ice_time: 0.0, avg_dtls_time: 0.0, avg_packet_loss: 0.0,
    avg_jitter: 0.0, avg_bitrate: 0.0, avg_rtt: 0.0, codecs_used: [], resolutions: []
  };
  
  return new TableRow({
    children: [
      bodyCell(bNames[b] || b, t2Cols[0], { fill, bold: true, color: NAVY }),
      bodyCell(p.avg_ice_time ? `${p.avg_ice_time.toFixed(0)} ms` : "N/A", t2Cols[1], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.avg_dtls_time ? `${p.avg_dtls_time.toFixed(0)} ms` : "N/A", t2Cols[2], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.avg_rtt ? `${p.avg_rtt.toFixed(0)} ms` : "N/A", t2Cols[3], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.avg_packet_loss !== undefined ? `${(p.avg_packet_loss * 100).toFixed(2)}%` : "0.0%", t2Cols[4], { fill, align: AlignmentType.CENTER, color: p.avg_packet_loss > 0.02 ? RED : "1F2937" }),
      bodyCell(p.avg_jitter ? `${p.avg_jitter.toFixed(1)} ms` : "0.0 ms", t2Cols[5], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.avg_bitrate ? `${p.avg_bitrate.toFixed(0)} kbps` : "N/A", t2Cols[6], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.codecs_used?.length ? p.codecs_used.join(", ") : "N/A", t2Cols[7], { fill, align: AlignmentType.CENTER }),
      bodyCell(p.resolutions?.length ? p.resolutions.join(", ") : "N/A", t2Cols[8], { fill, align: AlignmentType.CENTER })
    ]
  });
});

const t2Table = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: t2Cols,
  rows: [
    new TableRow({
      children: [
        headerCell("Browser", t2Cols[0]),
        headerCell("ICE Time", t2Cols[1]),
        headerCell("DTLS Time", t2Cols[2]),
        headerCell("Avg RTT", t2Cols[3]),
        headerCell("Packet Loss", t2Cols[4]),
        headerCell("Jitter", t2Cols[5]),
        headerCell("Avg Bitrate", t2Cols[6]),
        headerCell("Codec Used", t2Cols[7]),
        headerCell("Resolutions", t2Cols[8])
      ]
    }),
    ...webrtcRows
  ]
});

// ── 4. Table 3: Action Performance by Browser ────────────────────────────
const t3Cols = [1660, 1100, 1100, 1100, 1100, 1100, 1100, 1100]; // sum = 9360
const actionList = [
  { key: "camera", name: "Camera Toggle" },
  { key: "mic", name: "Mic Toggle" },
  { key: "hand", name: "Hand Raise" },
  { key: "chat", name: "Chat Send" },
  { key: "screen_share", name: "Screen Share" },
  { key: "note_update", name: "Note Sync" },
  { key: "breakout_join", name: "Breakout Migration" },
  { key: "lobby_admit", name: "Lobby Admission" },
  { key: "force_mute", name: "Force Mute Action" }
];
const actionBrowsers = ["chrome", "safari", "firefox", "edge", "brave", "chrome_mobile", "safari_mobile"];

const actionRows = actionList.map((a, i) => {
  const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
  
  const cells = actionBrowsers.map((b) => {
    const actPerf = data.action_performance?.[a.key]?.[b];
    if (!actPerf) return bodyCell("N/A", t3Cols[1], { fill, align: AlignmentType.CENTER });
    
    return bodyCell(`${(actPerf.avg_latency || 0.0).toFixed(0)} ms (${(actPerf.success_rate || 0.0).toFixed(0)}%)`, t3Cols[1], {
      fill, align: AlignmentType.CENTER,
      color: actPerf.success_rate < 90 ? RED : TEAL
    });
  });

  return new TableRow({
    children: [
      bodyCell(a.name, t3Cols[0], { fill, bold: true, color: NAVY }),
      ...cells
    ]
  });
});

const t3Table = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: t3Cols,
  rows: [
    new TableRow({
      children: [
        headerCell("Action Type", t3Cols[0]),
        headerCell("Chrome", t3Cols[1]),
        headerCell("Safari", t3Cols[2]),
        headerCell("Firefox", t3Cols[3]),
        headerCell("Edge", t3Cols[4]),
        headerCell("Brave", t3Cols[5]),
        headerCell("Chrome M.", t3Cols[6]),
        headerCell("Safari M.", t3Cols[7])
      ]
    }),
    ...actionRows
  ]
});

// ── 5. Browser Compatibility Matrix ──────────────────────────────────────
const compCols = [2360, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700]; // sum = 9360
const compHeaders = ["Feature", "Chrome", "Safari", "Firefox", "Edge", "Brave", "Chrome M", "Safari M", "Samsung", "Firefox M", "Opera M"];
const compFeatures = [
  ["WebRTC Join", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
  ["Camera Toggle", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
  ["Mic Toggle", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
  ["Screen Share", "✅", "✅", "✅", "✅", "✅", "❌", "❌", "❌", "❌", "❌"],
  ["Simulcast (3 layers)", "✅", "❌", "❌", "✅", "✅", "❌", "❌", "❌", "❌", "❌"],
  ["Simulcast (2 layers)", "❌", "✅", "✅", "❌", "❌", "✅", "✅", "✅", "✅", "✅"],
  ["AV1 Codec", "✅", "❌", "❌", "✅", "✅", "❌", "❌", "❌", "❌", "❌"],
  ["VP9 Codec", "✅", "❌", "✅", "✅", "✅", "✅", "❌", "✅", "❌", "✅"],
  ["H.264 Codec", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
  ["Adaptive Bitrate", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"]
];

const compRows = compFeatures.map((row, i) => {
  const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
  return new TableRow({
    children: [
      bodyCell(row[0], compCols[0], { fill, bold: true, color: NAVY }),
      ...row.slice(1).map((val, idx) => bodyCell(val, compCols[idx + 1], { fill, align: AlignmentType.CENTER, color: val === "✅" ? GREEN : RED }))
    ]
  });
});

const compTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: compCols,
  rows: [
    new TableRow({
      children: compHeaders.map((h, idx) => headerCell(h, compCols[idx]))
    }),
    ...compRows
  ]
});

// ── 6. Cross-Confirmation Propagation Latency ─────────────────────────────
const obsCols = [3000, 2000, 2180, 2180]; // sum = 9360 (CONTENT_WIDTH)
const obsActionList = [
  { key: "camera", name: "Camera Toggle" },
  { key: "mic", name: "Mic Toggle" },
  { key: "hand", name: "Hand Raise" },
  { key: "chat", name: "Chat Send" },
  { key: "screen_share", name: "Screen Share" }
];

const obsRows = obsActionList.map((a, i) => {
  const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
  const stats = data.observation_stats?.performance?.[a.key] || { count: 0, avg_latency: 0.0, p95_latency: 0.0 };
  
  return new TableRow({
    children: [
      bodyCell(a.name, obsCols[0], { fill, bold: true, color: NAVY }),
      bodyCell(stats.count, obsCols[1], { fill, align: AlignmentType.CENTER }),
      bodyCell(stats.count > 0 ? `${stats.avg_latency.toFixed(1)} ms` : "N/A", obsCols[2], { fill, align: AlignmentType.CENTER }),
      bodyCell(stats.count > 0 ? `${stats.p95_latency.toFixed(1)} ms` : "N/A", obsCols[3], { fill, align: AlignmentType.CENTER })
    ]
  });
});

const obsTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: obsCols,
  rows: [
    new TableRow({
      children: [
        headerCell("Action Type", obsCols[0]),
        headerCell("Observations Count", obsCols[1]),
        headerCell("Avg Propagation Latency", obsCols[2]),
        headerCell("95% Propagation Latency", obsCols[3])
      ]
    }),
    ...obsRows
  ]
});

// ── 7. Error Log & System Failures ─────────────────────────────────────────
const errorCols = [1800, 1000, 1200, 1500, 2660, 1200]; // sum = 9360 (CONTENT_WIDTH)
const errors = data.errors || [];
let errorTable;

if (errors.length === 0) {
  errorTable = new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [
      new TableRow({
        children: [
          bodyCell("No system errors or WebRTC failures were logged during this test run.", CONTENT_WIDTH, {
            fill: LIGHT,
            align: AlignmentType.CENTER,
            color: GREEN,
            bold: true
          })
        ]
      })
    ]
  });
} else {
  const errorRows = errors.map((err, i) => {
    const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
    let timeStr = err.ts || "";
    if (timeStr && timeStr.includes("T")) {
      try {
        const parts = timeStr.split("T");
        if (parts.length > 1) {
          timeStr = parts[1].substring(0, 8);
        }
      } catch (e) {}
    }
    
    return new TableRow({
      children: [
        bodyCell(timeStr, errorCols[0], { fill, align: AlignmentType.CENTER }),
        bodyCell(err.bot_id || "N/A", errorCols[1], { fill, align: AlignmentType.CENTER }),
        bodyCell(err.name || "N/A", errorCols[2], { fill }),
        bodyCell(err.action || "N/A", errorCols[3], { fill }),
        bodyCell(err.error || "N/A", errorCols[4], { fill, color: RED }),
        bodyCell(err.browser || "unknown", errorCols[5], { fill, align: AlignmentType.CENTER })
      ]
    });
  });

  errorTable = new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: errorCols,
    rows: [
      new TableRow({
        children: [
          headerCell("Time", errorCols[0]),
          headerCell("Bot ID", errorCols[1]),
          headerCell("Bot Name", errorCols[2]),
          headerCell("Action/Stage", errorCols[3]),
          headerCell("Error Message", errorCols[4]),
          headerCell("Browser", errorCols[5])
        ]
      }),
      ...errorRows
    ]
  });
}

// ── Helper heading builders ─────────────────────────────────────────────
function sectionHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: TEAL, space: 4 } },
    children: [new TextRun({ text })],
  });
}

// ── Document Assembly ───────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Calibri", size: 22, color: "1F2937" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Calibri", color: NAVY },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: "Calibri", color: TEAL },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BORDER_COLOR, space: 4 } },
          children: [
            new TextRun({ text: "Konn3ct Different — Advanced Multi-Browser Load Test Report", size: 16, color: GREY }),
            new TextRun({ text: "\t" }),
            new TextRun({ text: `Room: ${data.config?.room ?? "N/A"}`, size: 16, color: GREY }),
          ],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Page ", size: 16, color: GREY }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY }),
            new TextRun({ text: " of ", size: 16, color: GREY }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: GREY }),
          ],
        })],
      }),
    },
    children: [
      new Paragraph({
        spacing: { after: 60 },
        children: [new TextRun({ text: "Konn3ct Different Load Test Report", bold: true, size: 44, color: NAVY })],
      }),
      new Paragraph({
        spacing: { after: 280 },
        children: [new TextRun({
          text: `Room "${data.config?.room ?? "N/A"}"  •  Generated ${fmtDate(new Date().toISOString())}`,
          size: 20, color: GREY,
        })],
      }),

      sectionHeading("Executive Summary Dashboard"),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: `This report details the execution and WebRTC/actions analysis of the Konn3ct different load test suite simulating ${data.total_bots} bots across 8 distinct browser types, 3 device profiles (Desktop, Mobile, Tablet) and 5 operating systems.`,
          size: 20,
        })],
      }),
      statsTable,

      sectionHeading("Browser & Device Distribution Dashboard"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "Detailed breakdown of simulated users, their OS/device groups, and connection join success rates.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      t1Table,

      sectionHeading("Browser Compatibility Matrix"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "WebRTC and media capability feature sets simulated across browser cohorts.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      compTable,

      sectionHeading("WebRTC Performance by Browser"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "Detailed WebRTC stats including ICE connection delays, DTLS handshakes, and packet loss/jitter metrics.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      t2Table,

      sectionHeading("Action Performance by Browser"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "Average event propagation latencies and success percentages for client interactions.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      t3Table,

      sectionHeading("Cross-Confirmation & Event Propagation Delay"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: `Event propagation latency metrics calculated from ${data.observation_stats?.total_observed || 0} cross-confirmation observations where other bots verified broadcasts.`,
          size: 20, color: GREY, italics: true,
        })],
      }),
      obsTable,

      sectionHeading("Error Log & System Failures"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "Log of system errors, WebRTC signaling failures, ICE failures, or protocol timeouts captured during the test.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      errorTable,

      sectionHeading("Comprehensive Action Log"),
      new Paragraph({
        spacing: { after: 160 },
        children: [
          new TextRun({ text: "The complete, granular log containing every single bot interaction has been successfully exported to: ", size: 20 }),
          new TextRun({ text: `${data.csv_path || "action_log.csv"}`, bold: true, size: 20, color: TEAL })
        ]
      })
    ]
  }]
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Document written: ${outputPath}`);
});
