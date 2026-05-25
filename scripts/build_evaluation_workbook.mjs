import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(root, "outputs");
const outputFile = path.join(outputDir, "opensearch-search-evaluation-2.19.3.xlsx");
const matrixFile = path.join(outputDir, "search-matrix-results.json");

const matrix = JSON.parse(await fs.readFile(matrixFile, "utf8"));
const workbook = Workbook.create();

function colName(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function asText(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value, null, 0);
  return String(value);
}

function displayTerminology(value) {
  return asText(value)
    .replaceAll("误命中", "多命中")
    .replaceAll("漏命中", "少命中")
    .replaceAll("干扰命中", "多命中")
    .replaceAll("干扰行", "多命中行")
    .replaceAll("为什么是干扰", "为什么是多命中");
}

function writeSheet(name, headers, rows, widths = [], options = {}) {
  const ws = workbook.worksheets.add(name);
  const values = [headers, ...rows];
  const endCol = colName(headers.length);
  ws.getRange(`A1:${endCol}${values.length}`).values = values;
  ws.freezePanes.freezeRows(1);
  const header = ws.getRange(`A1:${endCol}1`);
  header.format.font.bold = true;
  header.format.font.color = "#FFFFFF";
  header.format.fill.color = options.headerColor || "#254E70";
  header.format.wrapText = true;
  const body = ws.getRange(`A2:${endCol}${Math.max(values.length, 2)}`);
  body.format.wrapText = true;
  body.format.verticalAlignment = "Top";
  widths.forEach((width, idx) => {
    ws.getRange(`${colName(idx + 1)}:${colName(idx + 1)}`).format.columnWidthPx = width;
  });
  return ws;
}

function colorRecommendationRows(ws, rows, recommendationColIndex, startRow = 2) {
  const colors = {
    "推荐": "#DFF1E3",
    "可用但有限制": "#FFF2CC",
    "不推荐": "#FCE4D6",
    "不可用": "#F4CCCC",
    "不适用": "#E7E6E6",
  };
  rows.forEach((row, idx) => {
    const rec = row[recommendationColIndex];
    const color = colors[rec];
    if (!color) return;
    const excelRow = startRow + idx;
    ws.getRange(`A${excelRow}:${colName(row.length)}${excelRow}`).format.fill.color = color;
  });
}

function shortLines(values, limit = 4) {
  const items = values.filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  return items.map((value) => String(value)).join("\n");
}

function uniqueLines(values) {
  const seen = new Set();
  const lines = [];
  for (const value of values || []) {
    const text = String(value ?? "").trimEnd();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    lines.push(text);
  }
  return lines;
}

function normMac(value) {
  return String(value || "").toLowerCase().replace(/[^0-9a-f]/g, "");
}

function sampleDataForField(field, limit = 5) {
  const rows = (matrix.test_data || []).filter((item) => item.field === field);
  const seen = new Set();
  const values = [];
  for (const row of rows) {
    const value = row.line_no ? `L${row.line_no}: ${row.stored_value}` : row.stored_value;
    if (!seen.has(value)) {
      seen.add(value);
      values.push(value);
    }
  }
  return shortLines(values, limit);
}

function hitDetailLines(details, filter = null, withReason = false) {
  const lines = [];
  for (const detail of details || []) {
    if (filter && !filter(detail)) continue;
    const matchedLines = detail.matched_lines || [];
    if (matchedLines.length) {
      for (const line of matchedLines) {
        if (filter && !filter(detail, line)) continue;
        lines.push(withReason ? detailContentLine(detail, line) : `L${line.line}: ${line.text}`);
      }
    } else if (detail.field_value) {
      lines.push(withReason ? detailContentLine(detail) : detail.field_value);
    }
  }
  return uniqueLines(lines);
}

function highlightLines(details) {
  const lines = [];
  for (const detail of details || []) {
    for (const fragment of detail.highlight_fragments || []) {
      lines.push(fragment);
    }
  }
  return lines;
}

function detailContentLine(detail, line = null) {
  const reason = line?.reason || detail.interference_reason || "";
  const content = line ? `L${line.line}: ${line.text}` : detail.field_value;
  if (!content) return "";
  return reason ? `${content}\n  原因：${reason}` : content;
}

function fieldsForCase(caseItem) {
  const fields = [];
  for (const field of [caseItem.field, caseItem.source_field]) {
    if (!field || field.startsWith("推荐组合")) continue;
    fields.push(field);
  }
  return [...new Set(fields)];
}

function isRelevantTestData(row, caseItem) {
  const value = String(row.stored_value || "");
  if (!row.line_no) return true;
  const query = String(caseItem.input_value || "");
  const lowerValue = value.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const queryMac = normMac(query);
  const valueMac = normMac(value);
  if (lowerQuery && lowerValue.includes(lowerQuery)) return true;
  if (queryMac.length >= 4 && valueMac.includes(queryMac)) return true;
  if (caseItem.input_type?.includes("MAC")) {
    const octets = queryMac.match(/.{1,2}/g) || [];
    return octets.some((octet) => octet.length === 2 && valueMac.includes(octet));
  }
  return false;
}

function testDataLinesForIds(caseItem, ids) {
  const fields = fieldsForCase(caseItem);
  const lines = [];
  for (const docId of ids || []) {
    let rows = (matrix.test_data || []).filter((row) => row.index === caseItem.index && row.doc_id === docId && fields.includes(row.field));
    if (!rows.length && caseItem.source_field) {
      rows = (matrix.test_data || []).filter((row) => row.index === caseItem.index && row.doc_id === docId && row.source_field === caseItem.source_field);
    }
    if (!rows.length) {
      rows = (matrix.test_data || []).filter((row) => row.index === caseItem.index && row.doc_id === docId);
    }
    const relevantRows = rows.filter((row) => isRelevantTestData(row, caseItem));
    for (const row of relevantRows.length ? relevantRows : rows) {
      const prefix = row.line_no ? `L${row.line_no}: ` : "";
      lines.push(`${prefix}${row.stored_value}`);
    }
  }
  return uniqueLines(lines);
}

function expectedLines(caseItem) {
  return testDataLinesForIds(caseItem, caseItem.expected_ids || []);
}

function actualLines(caseItem) {
  return hitDetailLines(caseItem.hit_details || []);
}

function missingLines(caseItem) {
  return testDataLinesForIds(caseItem, caseItem.missing_ids || []);
}

function extraLines(caseItem) {
  const details = (caseItem.interference_hit_details || []).length
    ? caseItem.interference_hit_details
    : (caseItem.hit_details || []).filter((detail) => detail.is_intended === false);
  return hitDetailLines(details, null, true);
}

function compactExplanation(caseItem) {
  const parts = [];
  if ((caseItem.missing_ids || []).length) parts.push("存在少命中，详见少命中具体内容");
  if ((caseItem.unexpected_ids || []).length || (caseItem.interference_hit_details || []).length) {
    parts.push("存在多命中，详见多命中具体内容");
  }
  if ((caseItem.actual_ids || []).length && !caseItem.has_highlight) parts.push("有命中但无高亮");
  if (caseItem.line_required && (caseItem.line_hits || []).length === 0 && (caseItem.actual_ids || []).length) {
    parts.push("实际命中缺少行号证据");
  }
  return parts.length ? parts.join("；") : displayTerminology(caseItem.verdict);
}

function compactCell(caseItem) {
  if (!caseItem) return "不适用\n说明：没有对应实测 case";
  if (caseItem.error) {
    return [
      "预期命中：无",
      "实际命中：无",
      "少命中：无",
      "多命中：无",
      "高亮片段：无",
      `结论：${caseItem.recommendation}`,
      `说明：${displayTerminology(caseItem.verdict)}`,
    ].join("\n");
  }
  const expected = expectedLines(caseItem);
  const actual = actualLines(caseItem);
  const missing = missingLines(caseItem);
  const extra = extraLines(caseItem);
  const highlights = highlightLines(caseItem.hit_details || []);
  return [
    "预期命中：",
    shortLines(expected) || "无",
    "",
    "实际命中：",
    shortLines(actual) || "无",
    "",
    "少命中：",
    shortLines(missing) || "无",
    "",
    "多命中：",
    shortLines(extra) || "无",
    "",
    "高亮片段：",
    shortLines(highlights, 3) || "无高亮",
    "",
    `结论：${caseItem.recommendation}`,
    `说明：${compactExplanation(caseItem)}`,
  ].join("\n");
}

function caseLookupKey(field, inputId, searchMode) {
  return `${field}||${inputId}||${searchMode}`;
}

function buildCaseLookup(cases) {
  const lookup = new Map();
  for (const item of cases) {
    lookup.set(caseLookupKey(item.field, item.input_id, item.search_mode), item);
  }
  return lookup;
}

function recommendationCaseFor(fieldSpec, column) {
  if (!column.recommendedCaseId) return null;
  if (fieldSpec.index === "structured-devices-v1" && column.recommendedCaseId.startsWith("rec_structured")) {
    return cases.find((item) => item.case_id === column.recommendedCaseId);
  }
  if (fieldSpec.index === "device-configs-v1" && column.recommendedCaseId.startsWith("rec_config")) {
    return cases.find((item) => item.case_id === column.recommendedCaseId);
  }
  return null;
}

function compactGroupColors(group) {
  if (group.startsWith("纯IP")) return { dark: "#1F4E5F", light: "#D9EAF7", text: "#FFFFFF" };
  if (group.startsWith("IPv6")) return { dark: "#385723", light: "#E2F0D9", text: "#FFFFFF" };
  if (group.startsWith("前导0")) return { dark: "#7F6000", light: "#FFF2CC", text: "#FFFFFF" };
  if (group.startsWith("纯MAC")) return { dark: "#7030A0", light: "#EADCF8", text: "#FFFFFF" };
  if (group.startsWith("普通文本")) return { dark: "#9E480E", light: "#FCE4D6", text: "#FFFFFF" };
  if (group.startsWith("片段")) return { dark: "#7F1D1D", light: "#F4CCCC", text: "#FFFFFF" };
  return { dark: "#1F4E5F", light: "#D9EAF7", text: "#FFFFFF" };
}

function writeCompactSheet(caseLookup) {
  const columns = [
    { group: "纯IP 10.10.10.1", label: "term（精确）", inputId: "ipv4_exact", mode: "term" },
    { group: "纯IP 10.10.10.1", label: "match_phrase（精确）", inputId: "ipv4_exact", mode: "match_phrase" },
    { group: "纯IP 10.10.10.1", label: "wildcard（包含）", inputId: "ipv4_exact", mode: "wildcard" },
    {
      group: "纯IP 10.10.10.1",
      label: "结构化：term(ip_address/ip_keyword)\n+ match_phrase(text字段)\n配置：match_phrase(config)\n+ 应用层行号",
      recommendedCaseId: "rec_structured_ipv4_exact",
      configRecommendedCaseId: "rec_config_ipv4_exact",
    },
    { group: "IPv6 2001:db8::1", label: "term（精确）", inputId: "ipv6_exact", mode: "term" },
    { group: "前导0 IP 010.010.010.001", label: "term（精确）", inputId: "ipv4_leading_zero", mode: "term" },
    { group: "纯MAC 4a:a9:59:4b:b6:2f", label: "match（精确意图）", inputId: "mac_cross_4a", mode: "match" },
    { group: "纯MAC 4a:a9:59:4b:b6:2f", label: "match_phrase（精确意图）", inputId: "mac_cross_4a", mode: "match_phrase" },
    { group: "纯MAC 4a:a9:59:4b:b6:2f", label: "wildcard（包含）", inputId: "mac_cross_4a", mode: "wildcard" },
    {
      group: "纯MAC 4a:a9:59:4b:b6:2f",
      label: "结构化：match(mac/mac.mac)\n+ attributes.mac/description.mac\n配置：match(config.mac)\n+ config高亮/行号",
      recommendedCaseId: "rec_structured_mac_cross",
      configRecommendedCaseId: "rec_config_mac_cross",
    },
    { group: "普通文本 allow-admin", label: "match_phrase", inputId: "text_allow_admin", mode: "match_phrase" },
    { group: "普通文本 allow-admin", label: "wildcard", inputId: "text_allow_admin", mode: "wildcard" },
    { group: "普通文本 allow-admin", label: "match+fuzziness", inputId: "text_allow_admin", mode: "match_fuzzy" },
    {
      group: "普通文本 allow-admin",
      label: "配置文本：match_phrase(config)\n+ match(config.ngram)\n+ wildcard(config.wild)",
      recommendedCaseId: "rec_config_text_fuzzy",
    },
    { group: "片段 10.10.10", label: "wildcard", inputId: "partial_ip", mode: "wildcard" },
    { group: "片段 4a:a9", label: "wildcard", inputId: "partial_mac", mode: "wildcard" },
    { group: "片段 59", label: "match", inputId: "partial_mac_octet_59", mode: "match" },
    { group: "片段 gatew", label: "wildcard", inputId: "partial_gatew", mode: "wildcard" },
  ];
  const headers1 = ["字段类型", "存储的数据内容类别", "示例数据", ...columns.map((col) => col.group)];
  const headers2 = ["", "", "", ...columns.map((col) => col.label)];
  const rows = (matrix.field_specs || []).map((fieldSpec) => {
    const cells = columns.map((col) => {
      let item = null;
      if (col.recommendedCaseId || col.configRecommendedCaseId) {
        const recId = fieldSpec.index === "device-configs-v1" ? (col.configRecommendedCaseId || col.recommendedCaseId) : col.recommendedCaseId;
        item = recommendationCaseFor(fieldSpec, { recommendedCaseId: recId || "" });
      } else {
        item = caseLookup.get(caseLookupKey(fieldSpec.field, col.inputId, col.mode));
      }
      return compactCell(item);
    });
    return [fieldSpec.field_type, fieldSpec.stored_shape, sampleDataForField(fieldSpec.field), ...cells];
  });
  const ws = workbook.worksheets.add("07_紧凑交叉对比");
  const values = [headers1, headers2, ...rows];
  const endCol = colName(headers1.length);
  ws.getRange(`A1:${endCol}${values.length}`).values = values;
  ws.freezePanes.freezeRows(2);
  ws.freezePanes.freezeColumns(3);
  ws.getRange(`A1:${endCol}2`).format.font.bold = true;
  ws.getRange("A1:C1").format.fill.color = "#1F4E5F";
  ws.getRange("A1:C1").format.font.color = "#FFFFFF";
  ws.getRange("A2:C2").format.fill.color = "#D9EAF7";
  ws.getRange(`A2:${endCol}2`).format.rowHeightPx = 88;
  ws.getRange(`A1:${endCol}${values.length}`).format.wrapText = true;
  ws.getRange(`A1:${endCol}${values.length}`).format.verticalAlignment = "Top";
  [90, 280, 460, ...columns.map(() => 330)].forEach((width, idx) => {
    ws.getRange(`${colName(idx + 1)}:${colName(idx + 1)}`).format.columnWidthPx = width;
  });
  for (let i = 0; i < columns.length;) {
    let j = i + 1;
    while (j < columns.length && columns[j].group === columns[i].group) j++;
    const startCol = colName(4 + i);
    const endGroupCol = colName(4 + j - 1);
    const colors = compactGroupColors(columns[i].group);
    ws.getRange(`${startCol}1:${endGroupCol}1`).format.fill.color = colors.dark;
    ws.getRange(`${startCol}1:${endGroupCol}1`).format.font.color = colors.text;
    ws.getRange(`${startCol}2:${endGroupCol}2`).format.fill.color = colors.light;
    ws.getRange(`${startCol}2:${endGroupCol}2`).format.font.color = "#1F1F1F";
    if (j - i > 1) {
      ws.mergeCells(`${startCol}1:${endGroupCol}1`);
    }
    i = j;
  }
  return ws;
}

const cases = matrix.cases || [];
const caseLookup = buildCaseLookup(cases);

const summaryByRecommendation = ["推荐", "可用但有限制", "不推荐", "不可用", "不适用"].map((name) => [
  name,
  cases.filter((item) => item.recommendation === name).length,
]);
const summaryRows = [
  ["OpenSearch 版本", matrix.opensearch.version, "build_hash", matrix.opensearch.build_hash],
  ["实测 case 数", matrix.matrix_dimensions.case_count, "字段数", matrix.matrix_dimensions.field_count],
  ["输入数", matrix.matrix_dimensions.input_count, "搜索方式数", matrix.matrix_dimensions.search_mode_count],
  ["生成时间", matrix.generated_at, "数据来源", "outputs/search-matrix-results.json"],
  ["核心结论", "Excel 明细每行均来自真实 OpenSearch 查询或实际执行错误/不适用记录", "非结构化行号", "由 _source.config 按输入类型二次计算"],
  ...summaryByRecommendation.map(([name, count]) => [`推荐等级=${name}`, count, "", ""]),
];
writeSheet(
  "00_结论总览",
  ["项目", "值", "补充项", "补充值"],
  summaryRows,
  [180, 420, 160, 520],
  { headerColor: "#1F4E5F" },
);

const testDataRows = (matrix.test_data || []).map((item) => [
  item.index,
  item.doc_id,
  item.field,
  item.field_type,
  item.source_field,
  item.stored_shape,
  item.line_no,
  item.stored_value,
]);
writeSheet(
  "01_测试数据",
  ["索引", "文档ID", "字段", "字段类型", "源字段", "存储形态", "config行号", "实际存储值/行文本"],
  testDataRows,
  [170, 100, 180, 90, 130, 260, 90, 620],
);

const configRows = (matrix.field_config || []).map((item) => [
  item.index,
  item.field,
  item.type,
  item.analyzer,
  item.search_analyzer,
  item.normalizer,
  item.term_vector,
  item.subfields,
]);
writeSheet(
  "02_字段配置",
  ["索引", "字段/analysis", "类型", "analyzer/配置", "search_analyzer", "normalizer", "term_vector", "子字段"],
  configRows,
  [170, 260, 110, 520, 160, 150, 130, 220],
);

const detailRows = cases.map((item) => [
  item.case_id,
  item.index,
  item.field,
  item.field_type,
  item.stored_shape,
  item.input_value,
  item.input_type,
  item.search_mode,
  item.dsl_summary,
  asText(item.expected_ids),
  asText(item.actual_ids),
  asText(item.unexpected_ids),
  asText(item.missing_ids),
  item.has_highlight ? "是" : "否",
  asText(item.highlight_ids),
  asText(item.line_hits),
  item.status,
  item.recommendation,
  displayTerminology(item.verdict),
  item.error ? asText(item.error) : "",
  displayTerminology(item.hit_details || []),
  displayTerminology(item.interference_hit_details || []),
]);
const detailSheet = writeSheet(
  "03_交叉验证明细",
  ["case_id", "索引", "字段", "字段类型", "存储形态", "测试输入", "输入类型", "搜索模式", "DSL摘要", "预期命中", "实际命中", "多命中", "少命中", "是否高亮", "高亮文档", "行号证据", "HTTP状态", "推荐等级", "验证结论", "错误/不适用原因", "命中具体数据", "多命中具体数据"],
  detailRows,
  [280, 170, 190, 95, 280, 150, 130, 130, 260, 160, 160, 160, 160, 90, 150, 520, 90, 120, 520, 620, 620, 620],
  { headerColor: "#17365D" },
);
colorRecommendationRows(detailSheet, detailRows, 17);

const dslRows = cases.map((item) => [
  item.case_id,
  item.index,
  item.field,
  item.input_value,
  item.search_mode,
  item.dsl_summary,
  JSON.stringify(item.dsl, null, 2),
]);
writeSheet(
  "04_DSL报文明细",
  ["case_id", "索引", "字段", "测试输入", "搜索模式", "DSL摘要", "完整DSL"],
  dslRows,
  [280, 170, 190, 150, 130, 260, 780],
);

const limitationRows = (matrix.limitations || []).map((item) => [
  displayTerminology(item.scenario),
  displayTerminology(item.limitation),
  displayTerminology(item.suggestion),
]);
writeSheet(
  "05_限制与反例",
  ["场景", "限制/反例", "建议"],
  limitationRows,
  [300, 620, 620],
  { headerColor: "#7F6000" },
);

const pivotRows = (matrix.pivot_summary || []).map((item) => [
  item.field_type,
  item.input_type,
  item.search_mode,
  item.total,
  item.recommended,
  item.usable_limited,
  item.not_recommended,
  item.unavailable,
  item.not_applicable,
  item.success_rate,
  item.overall_recommendation,
]);
const pivotSheet = writeSheet(
  "06_透视汇总",
  ["字段类型", "输入类型", "搜索模式", "总数", "推荐", "可用但有限制", "不推荐", "不可用", "不适用", "可用率", "总体推荐等级"],
  pivotRows,
  [100, 140, 130, 80, 80, 120, 90, 90, 90, 90, 140],
);
colorRecommendationRows(pivotSheet, pivotRows, 10);

writeCompactSheet(caseLookup);

const interferenceRows = [];
for (const item of cases) {
  for (const detail of item.interference_hit_details || []) {
    if ((detail.matched_lines || []).length) {
      for (const line of detail.matched_lines) {
        interferenceRows.push([
          item.case_id,
          item.field,
          item.input_value,
          item.search_mode,
          `L${line.line}: ${line.text}`,
          displayTerminology(detail.interference_reason || line.reason || item.verdict),
          item.recommendation,
          "优先使用 IP/MAC 专用字段或推荐组合；片段搜索必须明确标识为模糊模式",
        ]);
      }
    } else {
      interferenceRows.push([
        item.case_id,
        item.field,
        item.input_value,
        item.search_mode,
        detail.field_value || "",
        displayTerminology(detail.interference_reason || item.verdict),
        item.recommendation,
        "优先使用 IP/MAC 专用字段或推荐组合；片段搜索必须明确标识为模糊模式",
      ]);
    }
  }
}
const interferenceSheet = writeSheet(
  "08_多命中样例分析",
  ["case_id", "字段", "搜索输入", "搜索模式", "实际多命中数据", "为什么是多命中", "推荐等级", "规避建议"],
  interferenceRows,
  [280, 180, 150, 130, 620, 420, 120, 520],
  { headerColor: "#7F1D1D" },
);
colorRecommendationRows(interferenceSheet, interferenceRows, 6);

const hitDiffRows = cases.map((item) => [
  item.case_id,
  item.index,
  item.field,
  item.field_type,
  item.input_value,
  item.input_type,
  item.search_mode,
  item.recommendation,
  displayTerminology(item.verdict),
  shortLines(expectedLines(item)) || "无",
  shortLines(actualLines(item)) || "无",
  shortLines(missingLines(item)) || "无",
  shortLines(extraLines(item)) || "无",
]);
const hitDiffSheet = writeSheet(
  "09_命中差异明细",
  ["case_id", "索引", "字段", "字段类型", "测试输入", "输入类型", "搜索模式", "推荐等级", "验证结论", "预期命中具体内容", "实际命中具体内容", "少命中具体内容", "多命中具体内容"],
  hitDiffRows,
  [280, 170, 190, 95, 150, 130, 130, 120, 520, 620, 620, 620, 620],
  { headerColor: "#375623" },
);
colorRecommendationRows(hitDiffSheet, hitDiffRows, 7);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

for (const sheetName of [
  "00_结论总览",
  "01_测试数据",
  "02_字段配置",
  "03_交叉验证明细",
  "04_DSL报文明细",
  "05_限制与反例",
  "06_透视汇总",
  "07_紧凑交叉对比",
  "08_多命中样例分析",
  "09_命中差异明细",
]) {
  await workbook.render({ sheetName, range: "A1:K20", scale: 1 });
}

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputFile);
console.log(outputFile);
