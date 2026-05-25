# OpenSearch 索引配置与搜索能力说明书

## 1. 基本概念

OpenSearch 的搜索效果主要由三部分共同决定：

1. 字段类型：`ip`、`keyword`、`text`、`wildcard`、数值、日期等。
2. 分析链：`char_filter`、`tokenizer`、`token_filter`、`analyzer`、`normalizer`。
3. 查询类型：`term`、`match`、`match_phrase`、`wildcard`、`regexp`、`query_string`、`bool` 等。

同一个输入在不同字段类型和查询类型上的行为完全不同。例如：

- `term` 不分析查询输入，适合已经规范化的精确值。
- `match` 会分析查询输入，适合 `text` 字段，也可用于带 normalizer 的 `keyword` 字段。
- `match_phrase` 要求 token 顺序相邻，适合 IP 这类要避免部分误命中的文本精确搜索。
- `wildcard` 适合包含式匹配，但成本高。

## 2. 字段类型选择

### 2.1 `ip`

适合：

- 存储规范 IPv4/IPv6。
- 精确过滤、CIDR/range 类网络查询。
- 排除 `10.10.10.1` 误命中 `10.10.10.11`。

不适合：

- 存储带前导 0 的 IPv4 原文。
- 在包含 IP 的长文本中抽取命中。
- 作为高亮展示字段。
- 任意片段模糊搜索。

推荐查询：

```json
{ "term": { "ip_address": "10.10.10.1" } }
```

### 2.2 `keyword`

适合：

- 设备 ID、状态、厂商、纯 IP 字符串、纯 MAC 字符串。
- 精确匹配、聚合、排序。
- 搭配 normalizer 做大小写或格式归一。

不适合：

- 未加子字段时检索字段内部某个 IP/MAC 片段。
- 长文本全文搜索。

推荐配置：

```json
{
  "type": "keyword",
  "normalizer": "lowercase_norm",
  "fields": {
    "text": { "type": "text", "analyzer": "net_text" },
    "wild": { "type": "wildcard" }
  }
}
```

### 2.3 `text`

适合：

- 普通文本全文检索。
- 设备配置、描述、备注、命令行文本。
- 高亮。

关键点：

- 默认 analyzer 未必适合 IP/MAC，建议使用自定义 `net_text`。
- 对 MAC 跨格式精确搜索，增加 `mac` 子字段。
- 对任意片段搜索，增加 `wildcard` 或 `ngram` 子字段。

### 2.4 `wildcard`

适合：

- 日志、配置、长 keyword 的包含式查询。
- `*10.10.10*`、`*allow-admin*` 这类片段搜索。

限制：

- 不理解 IP/MAC 语义。
- MAC 跨格式匹配仍需要规范化字段或多格式查询。
- 前置通配和复杂模式成本高。

## 3. Analyzer 与 Normalizer

### 3.1 Analyzer

Analyzer 用于 `text` 字段，包含：

- `char_filter`: 分词前改写字符。
- `tokenizer`: 切分 token。
- `filter`: 小写、ngram、同义词等 token 处理。

本工程推荐的 `net_text` 保留 `.`, `:`, `-`, `_`，避免 IP/MAC 被拆碎。

### 3.2 Normalizer

Normalizer 用于 `keyword` 字段，产出单个 token。

典型用途：

- 小写归一：`ABC` 与 `abc` 匹配。
- MAC 分隔符归一：`4a:a9:...` 与 `4a-a9-...` 匹配。

注意：

- `term` 查询不会分析输入，客户端必须传入已经规范化的值。
- `match` 查询会走字段分析/normalizer，适合减少客户端预处理。

## 4. 查询类型说明

### 4.1 `term`

精确匹配倒排索引中的 token。

适合：

- `ip` 精确查询。
- `keyword` 精确查询。

风险：

- 对 `text` 字段不推荐，因为查询输入不分析。
- 对 normalized keyword 字段，输入必须与索引 token 一致。

### 4.2 `match`

分析查询输入后匹配。

适合：

- 普通全文搜索。
- `keyword` 字段配合 normalizer。
- `config.mac` 这种 MAC 规范化子字段。

### 4.3 `match_phrase`

分析查询输入后要求 token 顺序和邻接关系。

适合：

- IP 精确搜索。
- 命令短语搜索。
- 普通文本短语搜索。

### 4.4 `wildcard`

适合片段包含：

```json
{
  "wildcard": {
    "config.wild": {
      "value": "*allow-admin*",
      "case_insensitive": true
    }
  }
}
```

生产建议：

- 限制可查字段。
- 限制输入长度和通配符数量。
- 设置超时。
- 对高频需求优先考虑 ngram 子字段。

### 4.5 `regexp`

适合少量高级场景，不建议作为主查询路径。

风险：

- 复杂正则成本高。
- 用户输入需要严格转义和限制。

### 4.6 `query_string`

功能强，但对最终用户输入不友好。

风险：

- 特殊字符会被解释为查询语法。
- IP/MAC 中的 `:`, `.`, `-` 容易触发歧义。

推荐：

- 面向内部调试或高级用户。
- 面向普通用户时使用后端生成 DSL，不直接暴露 query_string。

## 5. 高亮

推荐使用 unified highlighter：

```json
{
  "highlight": {
    "fields": {
      "config": {
        "type": "unified",
        "number_of_fragments": 5
      }
    }
  }
}
```

实践建议：

- `text` 字段高亮最自然。
- keyword 子字段高亮可使用 `force_source`。
- `wildcard` 查询不一定总能得到理想高亮，必要时增加 `match_phrase` 分支帮助高亮。
- `ip` 类型不适合直接高亮，用原文 keyword/text 字段负责展示。

## 6. 行号

OpenSearch 原生搜索结果不返回 text 字段的行号。

推荐应用层后处理：

```python
lines = source_config.splitlines()
for line_no, line in enumerate(lines, 1):
    if pattern.search(line):
        ...
```

优点：

- 不新增独立字段。
- 保留原始配置。
- 可按 IP/MAC/普通文本使用不同边界规则。

缺点：

- 行号不参与排序。
- 需要应用层读取 `_source.config`。

如果要在 OpenSearch 中直接查询行号，需要将每行单独结构化：

- nested `lines.line_no`, `lines.text`
- 或单独 `config_lines` 索引

## 7. 针对 IP/MAC 的推荐输入分类

后端应先识别用户输入类型：

| 输入类型 | 判断方式 | 推荐查询 |
|---|---|---|
| IPv4 | 严格 IPv4 parser，拒绝误判普通数字 | `term ip` + `match_phrase text` |
| IPv6 | 严格 IPv6 parser | `term ip` + `match_phrase text` |
| MAC | 支持 `:`, `-`, `.`, 无分隔并规范化为 12 hex | `match mac` 或 `match field.mac` |
| 普通文本 | 其他输入 | `match`/`match_phrase` + 必要时 wildcard/ngram |
| 片段 | 用户选择模糊/包含模式 | `wildcard` 或 `ngram` 子字段 |

不要把 IP/MAC 的“模糊搜索”简单等同于 Levenshtein fuzziness。对网络标识来说，更常见的模糊是：

- 部分输入：`10.10.10`
- 格式差异：MAC 分隔符不同
- 大小写差异
- 包含在长文本中

这些应优先由 normalizer/analyzer/wildcard/ngram 解决。

## 8. 生产落地建议

1. 对用户输入先分类，再生成 DSL。
2. 精确模式和模糊模式分开，不要让精确 IP 自动退化成 wildcard。
3. `ip` 字段用于网络语义，`keyword/text` 字段用于展示、高亮、异常原文和内嵌文本检索。
4. MAC 统一使用 12 位小写 hex 作为内部规范形式。
5. 大字段 wildcard 查询要设置保护：字段白名单、超时、最大页数、最小输入长度。
6. 对配置文本，保留 `_source.config`，用于行号和原文展示。
7. 对特别高频的配置行号需求，再考虑拆行索引；不要一开始就牺牲写入复杂度和存储结构。

## 9. 干扰命中与规避

实际验证中需要把“OpenSearch 能命中”和“符合业务搜索本意”分开看。

典型干扰包括：

- 输入完整 MAC，但 `mac_flat` 子字段也会命中普通 12 位十六进制串，例如序列号 `4aa9594bb62f`。
- 输入 MAC 片段 `59`，可能命中时间 `2026-05-23 12:59:06`、端口 `Ethernet1/0/59`、`vlan 59`、版本 `4.9.59`。
- 输入精确 IP `10.10.10.1`，包含式查询可能误命中 `10.10.10.11`、`10.10.10.100`、`110.10.10.1`。
- 输入普通文本 `admin`，可能同时命中 `allow-admin`、`admin-down`、`administrator`。

规避建议：

- 精确 MAC 搜索优先走带业务语义的 `mac` 字段；不要把所有 12 位 hex 都当成 MAC。
- 如果非结构化配置必须严格排除序列号等 hex 干扰，需要写入时抽取独立 `mac` 字段，或建立行级/nested 结构并记录行号、行文本、抽取类型。
- 精确 IP 搜索使用 `ip` 字段或保持 IP 为完整 token 的 `match_phrase`，不要用 `*10.10.10.1*` 承担精确语义。
- 片段搜索、wildcard、ngram、fuzzy 应在 UI/API 层显式标记为“模糊”，并接受召回扩大。
