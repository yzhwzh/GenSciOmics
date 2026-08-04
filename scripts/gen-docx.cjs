const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, TableOfContents, LevelFormat
} = require("docx");

const brandBlue = "2E75B6";
const lightBg = "F2F7FB";
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

function hCell(text, w, fill) {
  return new TableCell({ borders, width: { size: w, type: WidthType.DXA },
    shading: { fill: fill || brandBlue, type: ShadingType.CLEAR }, margins: cellMargins,
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 18, font: "Arial" })] })]
  });
}
function dCell(text, w, opts) {
  return new TableCell({ borders, width: { size: w, type: WidthType.DXA },
    shading: opts?.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined, margins: cellMargins,
    children: [new Paragraph({ spacing: { before: 0, after: 0 },
      children: [new TextRun({ text, size: opts?.size || 18, font: "Arial", color: opts?.color || "333333" })]
    })]
  });
}

const COL = [1800, 900, 2400, 2400, 5500];

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: brandBlue },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "333333" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 1 } },
    ]
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1200, bottom: 1440, left: 1200 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: "GenSci v2 — 架构升级对比报告", size: 16, color: "999999" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "第 ", size: 16, color: "999999" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "999999" }), new TextRun({ text: " 页", size: 16, color: "999999" })] })] }) },
    children: [
      new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: "GenSci 新旧版本架构升级对比报告", size: 44, bold: true, color: brandBlue })] }),
      new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: "单细胞数据分析平台 · 2026年6月", size: 22, color: "666666" })] }),
      new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "本报告对比GenSci平台新旧版本在架构、安全、性能和维护性方面的差异，供评估升级决策参考。", size: 22, color: "444444" })] }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("一、代码架构对比")] }),
      new Table({ width: { size: 13000, type: WidthType.DXA }, columnWidths: [2200, 2700, 2700, 5400],
        rows: [
          new TableRow({ children: [hCell("维度", 2200), hCell("旧版 v1", 2700), hCell("新版 v2", 2700), hCell("改进说明", 5400)] }),
          ...[["后端文件数","1个 (api.py, 2507行)","15个模块","可维护性大幅提升"],
            ["最大后端文件","2507行（单体）","738行 (plots.py)","单一文件可控"],
            ["前端文件数","13个TS/TSX","35个TS/TSX","职责清晰分离"],
            ["最大前端文件","1379行 (AnalysisPage)","220行 (TissuePage)","每文件<300行"],
          ].map(r => new TableRow({ children: [dCell(r[0], 2200, {fill:lightBg}), dCell(r[1], 2700), dCell(r[2], 2700), dCell(r[3], 5400)] }))
        ]
      }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("二、已解决的风险")] }),
      new Table({ width: { size: 13000, type: WidthType.DXA }, columnWidths: COL,
        rows: [
          new TableRow({ children: [hCell("风险项", COL[0]), hCell("严重度", COL[1]), hCell("旧版问题", COL[2]), hCell("新版方案", COL[3]), hCell("通俗解释", COL[4])] }),
          ...[
            ["内存泄漏","🔴 HIGH","缓存无上限，长期运行OOM","LRU缓存上限1000条","服务器越跑越慢最终崩溃。新版限定最多装1000件，满了自动淘汰最旧的"],
            ["路径遍历攻击","🔴 HIGH","接口无路径校验，可读任意文件","Data/白名单校验","数据被偷读风险。新版设门禁白名单，只允许访问Data/内数据"],
            ["静默吞错误","🟠 MEDIUM","15+处except:pass","所有异常打印日志","出错了也不知道。新版每个错误都记录下来，快速定位"],
            ["单线程阻塞","🟠 MEDIUM","一个慢请求阻塞所有人","ThreadingHTTPServer","一个人卡全组。新版多线程，每个请求独立处理"],
            ["前端崩溃白屏","🟡 LOW","组件崩溃整个页面白屏","ErrorBoundary兜底","新版加安全气囊，单个图表崩溃不影响其他部分"],
            ["代码重复","🟡 LOW","基因解析逻辑重复6次","统一函数","改一处忘五处。新版只写一次，全生效"],
          ].map(r => new TableRow({ children: [
            dCell(r[0], COL[0], {fill:r[1].includes("HIGH")?"FDEDED":r[1].includes("MEDIUM")?"FFF8E5":"F2F7FB"}),
            dCell(r[1], COL[1]), dCell(r[2], COL[2]), dCell(r[3], COL[3]), dCell(r[4], COL[4])
          ]}))
        ]
      }),
      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("路径穿越（PATH TRAVERSAL）风险说明")] }),
      new Paragraph({ spacing: { before: 120 }, children: [new TextRun({ text: "什么是路径穿越？", size: 22, bold: true })] }),
      new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: "平台通过URL参数指定要分析的数据文件。如果没有做路径校验，攻击者可以将路径改为 ../../../etc/passwd 来读取系统密码文件，或读取其他研究组的未公开数据。", size: 20 })] }),
      new Paragraph({ spacing: { before: 120, after: 80 }, children: [new TextRun({ text: "新版防护机制", size: 22, bold: true })] }),
      ...[
        "白名单机制：只允许访问Data/目录下的文件",
        "路径规范化：将../../../等跳转符号解析为真实路径",
        "统一覆盖：所有12个文件读取接口使用同一套校验"
      ].map(t => new Paragraph({ spacing: { after: 40 }, numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: t, size: 20 })] })),
      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("后续安全增强措施")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "按投入产出比排序，可根据实际需求逐步实施：", size: 20 })] }),
      new Table({ width: { size: 12000, type: WidthType.DXA }, columnWidths: [3000, 1200, 1800, 6000],
        rows: [
          new TableRow({ children: [hCell("措施", 3000), hCell("成本", 1200), hCell("效果", 1800), hCell("说明", 6000)] }),
          ...[
            ["添加API密钥认证","低","🟢 大","给每个用户发密钥，防止外部直接调用API"],
            ["添加访问日志审计","低","🟢 中","记录谁在何时调了什么接口，出事可追溯"],
            ["限制POST写接口","中","🟢 大","里程碑添加等写操作仅管理员可执行"],
            ["HTTPS加密传输","中","🟢 大","防止数据在传输中被截获"],
            ["防火墙IP白名单","低","🟢 中","只允许公司内网IP访问"],
            ["限制请求参数大小","低","🟢 小","基因数量、文件大小设上限，防恶意请求"],
          ].map(r => new TableRow({ children: [dCell(r[0], 3000, {fill:lightBg}), dCell(r[1], 1200), dCell(r[2], 1800), dCell(r[3], 6000)] }))
        ]
      }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("三、响应速度对比")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "测试环境：同一服务器（224核CPU/1TB内存），各请求测试3次取平均值。轻量请求差异小是因两版业务逻辑相同，新版真正优势在并发场景。", size: 20 })] }),
      new Table({ width: { size: 10000, type: WidthType.DXA }, columnWidths: [3000, 2000, 2000, 3000],
        rows: [
          new TableRow({ children: [hCell("场景", 3000), hCell("旧版", 2000), hCell("新版", 2000), hCell("差异", 3000)] }),
          ...[
            ["轻量请求(5并发)","16ms","18ms","基本持平"],
            ["缓存命中","相同","相同","LRU命中率一致"],
            ["慢请求阻塞","会阻塞","不阻塞","✅ 新版关键优势"],
          ].map(r => new TableRow({ children: [dCell(r[0], 3000, {fill:lightBg}), dCell(r[1], 2000), dCell(r[2], 2000), dCell(r[3], 3000)] }))
        ]
      }),
      new Paragraph({ spacing: { before: 160 }, children: [new TextRun({ text: "并发场景对比：", size: 22, bold: true })] }),
      new Paragraph({ spacing: { after: 40 }, numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "旧版（单线程）：用户A加载UMAP图（3秒）→ 用户B的搜索请求必须等待3秒才能开始处理", size: 20 })] }),
      new Paragraph({ spacing: { after: 80 }, numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "新版（多线程）：用户A加载UMAP图（3秒）→ 用户B的搜索请求立即处理，互不阻塞", size: 20 })] }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("四、新版能做什么旧版不能")] }),
      new Table({ width: { size: 12000, type: WidthType.DXA }, columnWidths: [3000, 9000],
        rows: [
          new TableRow({ children: [hCell("能力", 3000), hCell("说明", 9000)] }),
          ...[
            ["多用户不阻塞","新版多线程，旧版单线程一人慢全队等"],
            ["安全暴露内网","路径白名单+完整日志，不怕路径穿越攻击"],
            ["持续运行不OOM","LRU缓存限制内存上限"],
            ["快速定位Bug","所有异常打日志，不再沉默"],
            ["方便扩展功能","加新API=一行路由+新文件"],
            ["前后端类型一致","后端改字段，前端编译立刻报错"],
            ["管理数据","Data/Human/Mouse/Monkey清晰分类"],
            ["未来升级框架","模块化设计，可升级到FastAPI"],
          ].map(r => new TableRow({ children: [dCell(r[0], 3000, {fill:lightBg}), dCell(r[1], 9000)] }))
        ]
      }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("五、总结")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "新版功能与旧版完全一致（API接口、前端页面、数据分析逻辑均不变），在以下四个维度全面超越旧版：", size: 22 })] }),
      ...[
        ["安全性：", "路径白名单校验防止数据泄露，所有异常可追溯"],
        ["并发能力：", "多线程架构支持多人同时使用不阻塞"],
        ["维护性：", "15个模块替代1个2500行单体文件，修Bug/加功能效率翻倍"],
        ["可扩展性：", "模块化设计方便后续升级和功能扩展"],
      ].map((r, i) => new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: r[0], size: 22, bold: true }), new TextRun({ text: r[1], size: 22 })] })),
      new Paragraph({ spacing: { before: 200, after: 80 }, children: [new TextRun({ text: "对于5-10人使用的内部平台，升级到新版最直接的体验改善是：多人同时操作时不再互相卡顿，服务器可以长期稳定运行无需频繁重启。", size: 24, bold: true, color: brandBlue })] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  const out = "GenSci_v2_架构升级对比报告.docx";
  fs.writeFileSync(out, buffer);
  console.log(`OK: ${out} (${(buffer.length/1024).toFixed(1)} KB)`);
});
