const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "GenSci Team";
pres.title = "GenSci — Single-Cell Data Analysis Platform";

// ─── Color palette ───
const C = {
  navy: "065A82",
  teal: "1C7293",
  lightTeal: "E8F4F8",
  accent: "F59E0B",
  white: "FFFFFF",
  dark: "1E293B",
  gray: "64748B",
  lightGray: "F1F5F9",
};

// ─── Helper: full-bleed bg shape ───
function bg(slide, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 5.625, fill: { color },
  });
}

// ─── Helper: bottom accent bar ───
function bottomBar(slide) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.425, w: 10, h: 0.2, fill: { color: C.teal },
  });
}

// ─── Helper: slide title ───
function slideTitle(slide, title) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.navy },
  });
  slide.addText(title, {
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 22, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
  });
}

// ─── Helper: card ───
function card(slide, x, y, w, h) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h, fill: { color: C.white },
    shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.08 },
  });
}

// ═══════════════════════════════════════════
// SLIDE 1: Title
// ═══════════════════════════════════════════
const s1 = pres.addSlide();
bg(s1, C.navy);
s1.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 1.6, w: 1.2, h: 0.06, fill: { color: C.accent },
});
s1.addText("GenSci", {
  x: 0.6, y: 1.8, w: 8.8, h: 0.8,
  fontSize: 44, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
s1.addText("Single-Cell Data Analysis Platform", {
  x: 0.6, y: 2.6, w: 8.8, h: 0.5,
  fontSize: 20, fontFace: "Calibri", color: C.lightTeal, margin: 0,
});
s1.addText("Development Timeline  ·  Architecture Evolution  ·  v1 → v2", {
  x: 0.6, y: 3.5, w: 8.8, h: 0.4,
  fontSize: 14, fontFace: "Calibri", color: C.gray, margin: 0,
});
bottomBar(s1);

// ═══════════════════════════════════════════
// SLIDE 2: Development Timeline (v1)
// ═══════════════════════════════════════════
const s2 = pres.addSlide();
bg(s2, C.lightGray);
slideTitle(s2, "Development Timeline — v1");

const v1Items = [
  ["Jun 11", "Initial commit — GenSci platform launched"],
  ["Jun 11", "UMAP visualization, gene expression gradients"],
  ["Jun 12", "Project rename: gensei → GenSci"],
  ["Jun 17", "Per-Sample & Aggregate page enhancements"],
  ["Jun 18", "Cell count label font & visual polish"],
];

v1Items.forEach((item, i) => {
  const y = 1.3 + i * 0.75;
  s2.addShape(pres.shapes.OVAL, {
    x: 0.8, y: y + 0.08, w: 0.18, h: 0.18, fill: { color: i === 0 ? C.accent : C.teal },
  });
  if (i < v1Items.length - 1) {
    s2.addShape(pres.shapes.LINE, {
      x: 0.89, y: y + 0.26, w: 0, h: 0.55,
      line: { color: C.teal, width: 1.5 },
    });
  }
  card(s2, 1.3, y - 0.05, 1.1, 0.35);
  s2.addText(item[0], {
    x: 1.3, y: y - 0.05, w: 1.1, h: 0.35,
    fontSize: 11, fontFace: "Calibri", color: C.navy, bold: true, align: "center", valign: "middle", margin: 0,
  });
  s2.addText(item[1], {
    x: 2.7, y: y - 0.05, w: 6.5, h: 0.35,
    fontSize: 13, fontFace: "Calibri", color: C.dark, valign: "middle", margin: 0,
  });
});
bottomBar(s2);

// ═══════════════════════════════════════════
// SLIDE 3: v2 Modular Refactor
// ═══════════════════════════════════════════
const s3 = pres.addSlide();
bg(s3, C.white);
slideTitle(s3, "v2 — Modular Refactor (Jun 18)");

const v2Points = [
  "Monolithic api.py → 15 domain modules",
  "ThreadingHTTPServer for concurrent requests",
  "LRU caching system (max 1000 entries)",
  "Unified frontend API layer (src/api/)",
  "AnalysisPage split into 12 sub-components",
  "Species-organized Data/ directory",
  "Path traversal protection & error logging",
];

s3.addText(
  v2Points.map((p, i) => ({
    text: p,
    options: { bullet: true, breakLine: true, fontSize: 14, color: C.dark },
  })),
  {
    x: 0.8, y: 1.3, w: 5.5, h: 3.5,
    fontFace: "Calibri", valign: "top", paraSpaceAfter: 6,
  }
);

// Right side: architecture diagram
card(s3, 6.8, 1.3, 2.6, 3.5);
s3.addText("Before", {
  x: 7, y: 1.6, w: 2.2, h: 0.4,
  fontSize: 13, fontFace: "Calibri", color: C.gray, align: "center", margin: 0,
});
s3.addShape(pres.shapes.RECTANGLE, {
  x: 7.5, y: 2.0, w: 1.2, h: 0.7, fill: { color: C.lightGray },
});
s3.addText("api.py", {
  x: 7.5, y: 2.0, w: 1.2, h: 0.7,
  fontSize: 9, fontFace: "Calibri", color: C.gray, align: "center", valign: "middle", margin: 0,
});
const arrowSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30" viewBox="0 0 40 30"><path d="M5 15 L35 15" stroke="#065A82" stroke-width="2.5" fill="none"/><polygon points="30,9 38,15 30,21" fill="#065A82"/></svg>';
s3.addImage({
  data: "image/svg+xml;base64," + Buffer.from(arrowSvg).toString("base64"),
  x: 7.7, y: 2.75, w: 0.8, h: 0.6,
});
s3.addText("After", {
  x: 7, y: 3.5, w: 2.2, h: 0.4,
  fontSize: 13, fontFace: "Calibri", color: C.teal, align: "center", margin: 0,
});
const mods = ["main.py", "routes.py", "scanner.py", "search.py", "analysis/"];
mods.forEach((m, i) => {
  const my = 3.85 + i * 0.25;
  s3.addShape(pres.shapes.RECTANGLE, {
    x: 7.1, y: my, w: 2.0, h: 0.2, fill: { color: C.teal, transparency: i === 4 ? 50 : 0 },
  });
  s3.addText(m, {
    x: 7.2, y: my - 0.02, w: 1.8, h: 0.22,
    fontSize: 7, fontFace: "Calibri", color: C.white, align: "center", valign: "middle", margin: 0,
  });
});
bottomBar(s3);

// ═══════════════════════════════════════════
// SLIDE 4: Current Architecture
// ═══════════════════════════════════════════
const s4 = pres.addSlide();
bg(s4, C.lightGray);
slideTitle(s4, "Current Architecture (v2)");

// Backend card
card(s4, 0.5, 1.2, 4.3, 3.8);
s4.addShape(pres.shapes.RECTANGLE, {
  x: 0.5, y: 1.2, w: 4.3, h: 0.45, fill: { color: C.navy },
});
s4.addText("Backend — Python 3", {
  x: 0.7, y: 1.25, w: 3.9, h: 0.35,
  fontSize: 14, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
const beItems = [
  ["main.py", "ThreadingHTTPServer entry"],
  ["routes.py", "15 API endpoints"],
  ["analysis/", "UMAP, stats, plots, expression"],
  ["scanner.py", "30s filesystem scan"],
  ["search.py", "Gene/disease/PMID search"],
];
beItems.forEach((item, i) => {
  const y = 1.85 + i * 0.55;
  s4.addShape(pres.shapes.RECTANGLE, {
    x: 0.75, y, w: 0.06, h: 0.35, fill: { color: C.teal },
  });
  s4.addText(item[0], {
    x: 1.0, y, w: 1.5, h: 0.35,
    fontSize: 11, fontFace: "Calibri", color: C.dark, bold: true, valign: "middle", margin: 0,
  });
  s4.addText(item[1], {
    x: 2.5, y, w: 2.1, h: 0.35,
    fontSize: 10, fontFace: "Calibri", color: C.gray, valign: "middle", margin: 0,
  });
});

// Frontend card
card(s4, 5.2, 1.2, 4.3, 3.8);
s4.addShape(pres.shapes.RECTANGLE, {
  x: 5.2, y: 1.2, w: 4.3, h: 0.45, fill: { color: C.teal },
});
s4.addText("Frontend — React 19 + TS 6", {
  x: 5.4, y: 1.25, w: 3.9, h: 0.35,
  fontSize: 14, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
const feItems = [
  ["src/api/", "client.ts, types.ts, domain APIs"],
  ["src/pages/", "Home, Tissue, Dataset, Analysis, Search"],
  ["src/components/", "12 analysis sub-components"],
  ["src/hooks/", "useTableFilter + custom hooks"],
  ["Tailwind v4", "Utility-first CSS framework"],
];
feItems.forEach((item, i) => {
  const y = 1.85 + i * 0.55;
  s4.addShape(pres.shapes.RECTANGLE, {
    x: 5.45, y, w: 0.06, h: 0.35, fill: { color: C.accent },
  });
  s4.addText(item[0], {
    x: 5.7, y, w: 1.5, h: 0.35,
    fontSize: 11, fontFace: "Calibri", color: C.dark, bold: true, valign: "middle", margin: 0,
  });
  s4.addText(item[1], {
    x: 7.2, y, w: 2.1, h: 0.35,
    fontSize: 10, fontFace: "Calibri", color: C.gray, valign: "middle", margin: 0,
  });
});
bottomBar(s4);

// ═══════════════════════════════════════════
// SLIDE 5: New Features
// ═══════════════════════════════════════════
const s5 = pres.addSlide();
bg(s5, C.white);
slideTitle(s5, "New Features (Jun 22)");

const features = [
  { title: "Column Header Filtering", desc: "useTableFilter hook + FilterDropdown\nCovers 8 tables across the platform\nSearch, Select All / Deselect All" },
  { title: "Performance Optimizations", desc: "Pre-computed uniqueValues (single-pass)\nuseDeferredValue for non-blocking UI\nReact.memo on FilterDropdown" },
  { title: "Large Table Protection", desc: "Auto-disables filters at 2,000+ rows\nPrevents browser freeze on big datasets" },
  { title: "MU Test Split Panels", desc: "Mean Expression / Expression %\nas independent resizable panels\nwith individual drag handles" },
  { title: "Chart Font Adaptation", desc: "Cell count labels scale dynamically:\n14pt / 12pt / 10pt by sample count" },
  { title: "Portal Dropdown Fix", desc: "Filter popups render via React portal\nNo more clipping by overflow containers" },
];

features.forEach((f, i) => {
  const col = i % 3;
  const row = Math.floor(i / 3);
  const x = 0.5 + col * 3.1;
  const y = 1.2 + row * 2.0;
  card(s5, x, y, 2.8, 1.7);
  s5.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h: 1.7, fill: { color: col === 0 ? C.navy : col === 1 ? C.teal : C.accent },
  });
  s5.addText(f.title, {
    x: x + 0.25, y: y + 0.12, w: 2.4, h: 0.35,
    fontSize: 12, fontFace: "Georgia", color: C.navy, bold: true, margin: 0,
  });
  s5.addText(f.desc, {
    x: x + 0.25, y: y + 0.5, w: 2.4, h: 1.1,
    fontSize: 9.5, fontFace: "Calibri", color: C.dark, margin: 0, valign: "top",
  });
});
bottomBar(s5);

// ═══════════════════════════════════════════
// SLIDE 6: v1 vs v2 Comparison
// ═══════════════════════════════════════════
const s6 = pres.addSlide();
bg(s6, C.lightGray);
slideTitle(s6, "v1 vs v2 — Architecture Comparison");

const headerRow = [
  { text: "Dimension", options: { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: "Calibri" } },
  { text: "v1 (Old)", options: { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: "Calibri" } },
  { text: "v2 (New)", options: { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: "Calibri" } },
];

const compRows = [
  ["Backend", "Single api.py", "15 domain modules"],
  ["Concurrency", "Single-thread", "ThreadingHTTPServer"],
  ["Cache", "None", "LRU (max 1000)"],
  ["API Layer", "Scattered fetch", "Unified src/api/"],
  ["Analysis Page", "Inline components", "12 sub-components"],
  ["Data Layout", "Flat directory", "Species-organized"],
  ["Types", "None", "Centralized types.ts"],
  ["Security", "None", "Path traversal protection"],
  ["Filtering", "None", "Full header filter system"],
];

const dataRows = compRows.map((r, i) => [
  { text: r[0], options: { fill: { color: i % 2 === 0 ? C.lightTeal : C.white }, color: C.dark, bold: true, fontSize: 10, fontFace: "Calibri" } },
  { text: r[1], options: { fill: { color: i % 2 === 0 ? C.lightTeal : C.white }, color: C.gray, fontSize: 10, fontFace: "Calibri" } },
  { text: r[2], options: { fill: { color: i % 2 === 0 ? C.lightTeal : C.white }, color: C.teal, bold: true, fontSize: 10, fontFace: "Calibri" } },
]);

s6.addTable([headerRow, ...dataRows], {
  x: 0.8, y: 1.3, w: 8.4,
  colW: [2.4, 2.8, 3.2],
  border: { pt: 0.5, color: "DEE2E6" },
  rowH: [0.4, ...compRows.map(() => 0.38)],
});
bottomBar(s6);

// ═══════════════════════════════════════════
// SLIDE 7: Technology Stack
// ═══════════════════════════════════════════
const s7 = pres.addSlide();
bg(s7, C.white);
slideTitle(s7, "Technology Stack");

// Left: Core (shared)
card(s7, 0.5, 1.2, 4.2, 3.8);
s7.addShape(pres.shapes.RECTANGLE, {
  x: 0.5, y: 1.2, w: 4.2, h: 0.45, fill: { color: C.navy },
});
s7.addText("v1 & v2 — Core Stack", {
  x: 0.7, y: 1.25, w: 3.8, h: 0.35,
  fontSize: 13, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
const coreStack = [
  "React 19 + TypeScript 6",
  "Tailwind CSS v4 + Vite 8",
  "Python 3 + anndata (.h5ad)",
  "matplotlib + seaborn + colorcet",
  "ECharts 6 — Interactive Viz",
];
s7.addText(
  coreStack.map(t => ({ text: t, options: { bullet: true, breakLine: true, fontSize: 13, color: C.dark } })),
  { x: 0.8, y: 1.9, w: 3.6, h: 2.8, fontFace: "Calibri", valign: "top", paraSpaceAfter: 10 }
);

// Right: v2 additions
card(s7, 5.3, 1.2, 4.2, 3.8);
s7.addShape(pres.shapes.RECTANGLE, {
  x: 5.3, y: 1.2, w: 4.2, h: 0.45, fill: { color: C.teal },
});
s7.addText("v2 Additions", {
  x: 5.5, y: 1.25, w: 3.8, h: 0.35,
  fontSize: 13, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
const v2Additions = [
  "ThreadingHTTPServer — concurrent requests",
  "LRU Cache — memory-safe (max 1000)",
  "TypeScript strict types — types.ts",
  "Custom hooks — useTableFilter",
  "Portal rendering — no UI clipping",
];
s7.addText(
  v2Additions.map(t => ({ text: t, options: { bullet: true, breakLine: true, fontSize: 13, color: C.teal } })),
  { x: 5.6, y: 1.9, w: 3.6, h: 2.8, fontFace: "Calibri", valign: "top", paraSpaceAfter: 10 }
);
bottomBar(s7);

// ═══════════════════════════════════════════
// SLIDE 8: Thank You
// ═══════════════════════════════════════════
const s8 = pres.addSlide();
bg(s8, C.navy);
s8.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 2.0, w: 1.2, h: 0.06, fill: { color: C.accent },
});
s8.addText("Thank You", {
  x: 0.6, y: 2.2, w: 8.8, h: 0.7,
  fontSize: 40, fontFace: "Georgia", color: C.white, bold: true, margin: 0,
});
s8.addText("GenSci — Built with Vibe Coding", {
  x: 0.6, y: 3.0, w: 8.8, h: 0.4,
  fontSize: 16, fontFace: "Calibri", color: C.lightTeal, margin: 0,
});
s8.addText("June 2026  ·  Claude Code + DeepSeek", {
  x: 0.6, y: 3.5, w: 8.8, h: 0.3,
  fontSize: 12, fontFace: "Calibri", color: C.gray, margin: 0,
});
bottomBar(s8);

// ─── Save ───
pres.writeFile({ fileName: "/data/yuanwuzhou/102.ClaudeCode/06.GenSci/GenSci_Dev_Report.pptx" })
  .then(() => console.log("DONE: GenSci_Dev_Report.pptx"))
  .catch(err => console.error("ERROR:", err));
