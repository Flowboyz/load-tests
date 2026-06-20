const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
  BorderStyle, WidthType, ShadingType, VerticalAlign, PageNumber,
  TabStopType, TabStopPosition,
} = require("docx");

const dataPath   = process.argv[2];
const outputPath = process.argv[3];

const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

// ── Page / colour constants ─────────────────────────────────────────────
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

// ── Reusable cell builders ──────────────────────────────────────────────
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
      children: [new TextRun({
        text: String(text), size: 18,
        color: opts.color || "1F2937", bold: opts.bold || false,
      })],
    })],
  });
}

// ── Stat card row (summary metrics) ─────────────────────────────────────
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

// ── Build summary stat cards ────────────────────────────────────────────
const cardWidth = Math.floor(CONTENT_WIDTH / 4);
const statsTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [cardWidth, cardWidth, cardWidth, cardWidth],
  rows: [
    new TableRow({
      children: [
        statCard("Bots Requested", data.requested_bots, NAVY),
        statCard("Successfully Joined", data.joined_count, GREEN),
        statCard("Failed", data.failed_count, data.failed_count > 0 ? RED : GREY),
        statCard("Success Rate", `${data.success_rate}%`, data.success_rate >= 90 ? GREEN : AMBER),
      ],
    }),
  ],
});

const statsTable2 = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [cardWidth, cardWidth, cardWidth, cardWidth],
  rows: [
    new TableRow({
      children: [
        statCard("Peak Concurrent", data.peak_active, TEAL),
        statCard("Test Duration", data.duration_str, NAVY),
        statCard("Reconnect Events", data.total_reconnect_events, data.total_reconnect_events > 0 ? AMBER : GREY),
        statCard("Avg Session Length", `${data.avg_duration}s`, NAVY),
      ],
    }),
  ],
});

// ── Config table ─────────────────────────────────────────────────────────
const cfg = data.config || {};
const configRows = [
  ["Room", cfg.room ?? "N/A"],
  ["Bots Requested", cfg.bots ?? "N/A"],
  ["Batch Size", cfg.batch ?? "N/A"],
  ["Stagger (seconds)", cfg.stagger ?? "N/A"],
  ["Max Concurrency", cfg.concurrency ?? "N/A"],
  ["Auto-leave (minutes)", cfg.auto_leave_minutes ? cfg.auto_leave_minutes : "Manual"],
  ["Chat Simulation", cfg.chat_enabled ? "Enabled" : "Disabled"],
  ["Camera Toggle", cfg.camera_enabled ? "Enabled" : "Disabled"],
  ["Mic Toggle", cfg.mic_enabled ? "Enabled" : "Disabled"],
  ["Hand Raise", cfg.hand_enabled ? "Enabled" : "Disabled"],
  ["Max Retries per Bot", cfg.max_retries ?? "N/A"],
];

const labelW = 3600, valueW = CONTENT_WIDTH - 3600;
const configTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [labelW, valueW],
  rows: configRows.map(([label, value], i) =>
    new TableRow({
      children: [
        bodyCell(label, labelW, { fill: i % 2 === 0 ? LIGHT : "FFFFFF", bold: true, color: NAVY }),
        bodyCell(String(value), valueW, { fill: i % 2 === 0 ? LIGHT : "FFFFFF" }),
      ],
    })
  ),
});

// ── Timeline table (sampled — show every Nth point to keep it readable) ──
const timeline = data.timeline || [];
const maxRows = 20;
const step = Math.max(1, Math.floor(timeline.length / maxRows));
const sampledTimeline = timeline.filter((_, i) => i % step === 0);

const tlCols = [2340, 2340, 2340, 2340];
const timelineTable = new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: tlCols,
  rows: [
    new TableRow({
      children: [
        headerCell("Elapsed Time", tlCols[0]),
        headerCell("Joined (cum.)", tlCols[1]),
        headerCell("Active Now", tlCols[2]),
        headerCell("Failed (cum.)", tlCols[3]),
      ],
    }),
    ...sampledTimeline.map((point, i) => {
      const mins = Math.floor(point.elapsed / 60);
      const secs = point.elapsed % 60;
      const timeStr = `${mins}m ${secs}s`;
      const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
      return new TableRow({
        children: [
          bodyCell(timeStr, tlCols[0], { fill }),
          bodyCell(point.joined, tlCols[1], { fill }),
          bodyCell(point.active, tlCols[2], { fill, color: TEAL, bold: true }),
          bodyCell(point.failed, tlCols[3], { fill, color: point.failed > 0 ? RED : GREY }),
        ],
      });
    }),
  ],
});

// ── Simple bar chart of active users over time (drawn with table cells) ──
function buildBarChart() {
  if (sampledTimeline.length === 0) return [];
  const maxActive = Math.max(...sampledTimeline.map(p => p.active), 1);
  const chartRows = sampledTimeline.map((point) => {
    const barWidthDxa = Math.max(60, Math.round((point.active / maxActive) * (CONTENT_WIDTH - 2400)));
    const labelW = 1400, valueW = 1000, barAreaW = CONTENT_WIDTH - labelW - valueW;
    const mins = Math.floor(point.elapsed / 60);
    const secs = point.elapsed % 60;
    return new TableRow({
      children: [
        new TableCell({
          borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
          width: { size: labelW, type: WidthType.DXA },
          margins: { top: 40, bottom: 40, left: 0, right: 80 },
          children: [new Paragraph({ children: [new TextRun({ text: `${mins}m${secs}s`, size: 14, color: GREY })] })],
        }),
        new TableCell({
          borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
          width: { size: barAreaW, type: WidthType.DXA },
          margins: { top: 40, bottom: 40, left: 0, right: 0 },
          children: [
            new Table({
              width: { size: barWidthDxa, type: WidthType.DXA },
              columnWidths: [barWidthDxa],
              rows: [new TableRow({ children: [
                new TableCell({
                  borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
                  width: { size: barWidthDxa, type: WidthType.DXA },
                  shading: { fill: TEAL, type: ShadingType.CLEAR },
                  margins: { top: 60, bottom: 60, left: 0, right: 0 },
                  children: [new Paragraph({ children: [] })],
                }),
              ] })],
            }),
          ],
        }),
        new TableCell({
          borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
          width: { size: valueW, type: WidthType.DXA },
          margins: { top: 40, bottom: 40, left: 80, right: 0 },
          children: [new Paragraph({ children: [new TextRun({ text: String(point.active), size: 16, bold: true, color: NAVY })] })],
        }),
      ],
    });
  });

  return [
    new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [1400, CONTENT_WIDTH - 2400, 1000],
      rows: chartRows,
    }),
  ];
}

// ── Failures table ────────────────────────────────────────────────────────
const failures = data.failures || [];
const REASON_LABELS = {
  prejoin_or_join_failed: "Could not join (prejoin/join API failed)",
  max_retries_exceeded:   "Connection kept dropping (max retries exceeded)",
  token_reacquire_failed: "Could not refresh session token",
  unknown:                "Unknown error",
};

const fCols = [900, 2400, 3060, 3000];
const failuresTable = failures.length === 0
  ? [new Paragraph({
      spacing: { before: 120, after: 120 },
      children: [new TextRun({ text: "No bot failures were recorded during this test. ✅", italics: true, color: GREEN, size: 20 })],
    })]
  : [new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: fCols,
      rows: [
        new TableRow({
          children: [
            headerCell("Bot ID", fCols[0]),
            headerCell("Name", fCols[1]),
            headerCell("Failure Reason", fCols[2]),
            headerCell("Time", fCols[3]),
          ],
        }),
        ...failures.map((f, i) => {
          const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
          return new TableRow({
            children: [
              bodyCell(`#${String(f.bot_id).padStart(4, "0")}`, fCols[0], { fill }),
              bodyCell(f.name || "Unknown", fCols[1], { fill }),
              bodyCell(REASON_LABELS[f.reason] || f.reason, fCols[2], { fill, color: RED }),
              bodyCell(f.ts ? new Date(f.ts).toLocaleTimeString() : "N/A", fCols[3], { fill }),
            ],
          });
        }),
      ],
    })];

// ── Reconnects table ─────────────────────────────────────────────────────
const reconnects = data.reconnects || [];
const rCols = [900, 3000, 1800, 3660];
const reconnectsTable = reconnects.length === 0
  ? [new Paragraph({
      spacing: { before: 120, after: 120 },
      children: [new TextRun({ text: "No reconnect attempts were recorded — all connections remained stable. ✅", italics: true, color: GREEN, size: 20 })],
    })]
  : [new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: rCols,
      rows: [
        new TableRow({
          children: [
            headerCell("Bot ID", rCols[0]),
            headerCell("Name", rCols[1]),
            headerCell("Attempt #", rCols[2]),
            headerCell("Time", rCols[3]),
          ],
        }),
        ...reconnects.map((r, i) => {
          const fill = i % 2 === 0 ? "FFFFFF" : LIGHT;
          return new TableRow({
            children: [
              bodyCell(`#${String(r.bot_id).padStart(4, "0")}`, rCols[0], { fill }),
              bodyCell(r.name || "Unknown", rCols[1], { fill }),
              bodyCell(r.attempt ?? "N/A", rCols[2], { fill, color: AMBER }),
              bodyCell(r.ts ? new Date(r.ts).toLocaleTimeString() : "N/A", rCols[3], { fill }),
            ],
          });
        }),
      ],
    })];

// ── Section heading helper ──────────────────────────────────────────────
function sectionHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: TEAL, space: 4 } },
    children: [new TextRun({ text })],
  });
}

function subHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text })],
  });
}

// ── Document assembly ─────────────────────────────────────────────────────
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
            new TextRun({ text: "py_guest — Konn3ct Load Test Report", size: 16, color: GREY }),
            new TextRun({ text: "\t" }),
            new TextRun({ text: `Room: ${cfg.room ?? "N/A"}`, size: 16, color: GREY }),
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
      // Title
      new Paragraph({
        spacing: { after: 60 },
        children: [new TextRun({ text: "Konn3ct Load Test Report", bold: true, size: 44, color: NAVY })],
      }),
      new Paragraph({
        spacing: { after: 280 },
        children: [new TextRun({
          text: `Room "${cfg.room ?? "N/A"}"  •  Generated ${fmtDate(new Date().toISOString())}`,
          size: 20, color: GREY,
        })],
      }),

      // Executive summary
      sectionHeading("Executive Summary"),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: `This report summarizes a simulated load test against the Konn3ct platform using ${data.requested_bots} automated bot participants. The test ran from ${fmtDate(data.started_at)} to ${fmtDate(data.finished_at)}, lasting ${data.duration_str}.`,
          size: 20,
        })],
      }),
      statsTable,
      new Paragraph({ spacing: { before: 160 }, children: [] }),
      statsTable2,

      // Test configuration
      sectionHeading("Test Configuration"),
      configTable,

      // Timeline
      sectionHeading("Participant Timeline"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: "Active concurrent users over the duration of the test, sampled at regular intervals.",
          size: 20, color: GREY, italics: true,
        })],
      }),
      ...buildBarChart(),
      new Paragraph({ spacing: { before: 240 }, children: [] }),
      subHeading("Detailed Timeline Data"),
      timelineTable,

      // Failures
      sectionHeading("Bot Failure Details"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: `${data.failed_count} of ${data.requested_bots} bots failed to join or maintain a stable session (${(100 - data.success_rate).toFixed(1)}% failure rate).`,
          size: 20, color: GREY,
        })],
      }),
      ...failuresTable,

      // Reconnects
      sectionHeading("Reconnection Events"),
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({
          text: `${data.total_reconnect_events} reconnection attempts were recorded across all bots, indicating network or server-side connection drops during the test.`,
          size: 20, color: GREY,
        })],
      }),
      ...reconnectsTable,
    ],
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Document written: ${outputPath}`);
});
