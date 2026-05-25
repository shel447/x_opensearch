# 设备搜索系统 OpenSearch 2.19.3 索引与查询方案

## 1. 目标与结论

目标是在 OpenSearch 2.19.3 中同时支持两类业务索引：

- 结构化索引：交换机、路由器、防火墙、AP 等设备表项，包含 `ip`、`keyword`、`text`、数值、时间等字段。
- 非结构化索引：设备配置，几十 KB 多行文本，全部内容优先放在单个 `config` 字段中。

核心能力要求：

- IP 精确搜索：输入 `10.10.10.1` 只命中 `10.10.10.1`，不能误命中 `10.10.10.11`。
- MAC 精确搜索：输入 `4a:a9:59:4b:b6:2f` 可命中 `4a-a9-59-4b-b6-2f`、`4aa9.594b.b62f`、`4aa9594bb62f`。
- 普通文本精确与模糊搜索。
- 搜索结果高亮。
- 对非结构化 `config` 文本，返回匹配行号。
- 尽可能少新增独立字段，优先使用 normalizer、analyzer、multi-field 子字段。

验证后的推荐结论：

1. 结构化索引保留业务主字段类型，但为关键字符串字段增加 multi-field 子字段。
2. `ip` 类型适合作为纯 IP 规范精确过滤字段，但不适合原文高亮、包含式搜索、带前导 0 IPv4、或 keyword/text 字段内嵌 IP 的场景。
3. MAC 跨格式精确匹配必须引入规范化能力：`keyword` 字段使用 `mac_norm` normalizer，`text/config` 子字段使用 `mac_flat` analyzer。
4. 非结构化配置索引可以不新增独立 `ip`、`mac` 字段，只在 `config` 上增加 `mac`、`wild`、`ngram` 子字段。
5. OpenSearch 原生 highlighter 可以返回片段高亮，但不能原生返回“第几行”；行号应由应用层基于 `_source.config` 二次计算。如果必须完全由索引层返回行号，需要把配置拆成 nested line 文档或单独行索引，这会新增独立结构。

## 2. 已验证版本与环境

本工程实际连接的 OpenSearch 节点返回：

```json
{
  "version": "2.19.3",
  "build_hash": "a90f864b8524bc75570a8461ccb569d2a4bfed42",
  "lucene_version": "9.12.2"
}
```

Docker 镜像使用 digest 固定：

- OpenSearch: `opensearchproject/opensearch@sha256:e96cc6ae1500a073d973c0906f30f7cf4d9c461f32f855f9242a2da933660cdd`
- OpenSearch Dashboards: `opensearchproject/opensearch-dashboards@sha256:19e0dd30c7086e933cf475726d92ccc98be26ced9f0c4e4a2a3ae6d9539280a3`

## 3. 推荐索引设计

### 3.1 结构化索引

索引文件：`opensearch/indices/structured-devices-v1.json`

关键字段：

| 字段 | 类型 | 作用 |
|---|---|---|
| `ip_address` | `ip` | 纯 IPv4/IPv6 规范精确过滤 |
| `ip_keyword` | `keyword` + `text/wild/ngram` 子字段 | 保留 IP 原始字符串，用于高亮、展示、包含式搜索、异常格式 |
| `mac` | `keyword` + `mac_norm` + 子字段 | MAC 跨格式精确匹配与展示 |
| `attributes` | `keyword` + `text/mac/wild/ngram` 子字段 | keyword 字段中包含 IP/MAC/普通文本时仍可检索 |
| `description` | `text` + `keyword/mac/wild/ngram` 子字段 | 普通文本、内嵌 IP/MAC、模糊搜索 |

为什么需要 `ip_keyword`：

- `ip` 类型可以准确区分 `10.10.10.1` 和 `10.10.10.11`。
- 但 `ip` 类型不是字符串全文字段，不能承担通用高亮和包含式检索。
- `010.010.010.001` 这类带前导 0 的 IPv4 字符串不应直接写入 `ip` 类型，应保留为 keyword/text 原文并在应用层规范化或标记异常。

### 3.2 非结构化配置索引

索引文件：`opensearch/indices/device-configs-v1.json`

主字段仍只有：

```json
{
  "config": {
    "type": "text",
    "analyzer": "net_text",
    "fields": {
      "mac": { "type": "text", "analyzer": "mac_flat" },
      "wild": { "type": "wildcard" },
      "ngram": { "type": "text", "analyzer": "net_ngram", "search_analyzer": "net_text" }
    }
  }
}
```

这样满足“优先不新增独立字段”的要求。`config.mac`、`config.wild`、`config.ngram` 是 multi-field 子字段，不改变业务文档结构。

## 4. 分析器与规范化器

### 4.1 `net_text`

用途：让 IP、IPv6、MAC、带中划线的命令词尽量保持为完整 token。

分词边界：

```json
{
  "type": "pattern",
  "pattern": "[^A-Za-z0-9_.:-]+"
}
```

示例：

```text
ip address 10.10.10.1 mac 4a-a9-59-4b-b6-2f
```

会产生：

```text
ip, address, 10.10.10.1, mac, 4a-a9-59-4b-b6-2f
```

因此 `match_phrase` 搜 `10.10.10.1` 不会误命中 `10.10.10.11`。

### 4.2 `mac_norm`

用于 `keyword` 字段，把 MAC 的 `:.-` 去掉并小写。

```json
{
  "type": "custom",
  "char_filter": ["mac_separator_strip"],
  "filter": ["lowercase"]
}
```

适用于 `mac` 这类纯 MAC keyword 字段。

注意：`term` 查询不会自动分析输入。如果使用 `term` 搜 MAC，客户端要先把输入 `4a:a9:59:4b:b6:2f` 规范化为 `4aa9594bb62f`；如果不想在客户端处理，使用 `match` 查询更稳。

### 4.3 `mac_flat`

用于 `text`/`config` 子字段，把文本中的 MAC 规范化为同一个 token。

示例：

```text
4a-a9-59-4b-b6-2f
4a:a9:59:4b:b6:2f
4aa9.594b.b62f
4aa9594bb62f
```

都会变成：

```text
4aa9594bb62f
```

注意：`mac_flat` 会去掉 `:.-`，不要拿它做 IP 搜索，否则 IPv4 也会被压扁。

## 5. 查询方案

### 5.1 结构化 IP 精确搜索

报文：`opensearch/search-requests/structured-exact-ip.json`

策略：

- `ip_address` 上用 `term`，负责纯 IP 字段精确匹配。
- `ip_keyword` 上用 `term`，负责原文 keyword 精确。
- `attributes.text`、`description` 上用 `match_phrase`，负责包含 IP 的 keyword/text 内容。

验证结果：

- 输入 `10.10.10.1`
- 命中 `dev-001`
- 不命中 `dev-002`，即没有误命中 `10.10.10.11`
- 有高亮

### 5.2 配置 IP 精确搜索

报文：`opensearch/search-requests/config-exact-ip.json`

策略：

- `config` 使用 `match_phrase`
- 高亮使用 unified highlighter
- 行号由应用层对 `_source.config` splitlines 后，用 IP 边界正则计算

验证结果：

- 输入 `10.10.10.1`
- 命中 `cfg-001` 第 3 行、`cfg-003` 第 4 行
- 不命中 `cfg-002` 中的 `10.10.10.11`
- 有高亮

### 5.3 结构化 MAC 跨格式精确搜索

报文：`opensearch/search-requests/structured-exact-mac-cross-format.json`

策略：

- `mac` keyword 字段使用 `match`，触发 normalizer。
- `mac.mac`、`attributes.mac`、`description.mac` 使用 `mac_flat` analyzer。

验证结果：

- 输入 `4a:a9:59:4b:b6:2f`
- 命中存储为 `4a-a9-59-4b-b6-2f` 的 `dev-001`
- 命中存储为 `4aa9594bb62f` 的 `dev-003`
- 有高亮

### 5.4 配置 MAC 跨格式精确搜索

报文：`opensearch/search-requests/config-exact-mac-cross-format.json`

策略：

- 查询 `config.mac`
- 使用 `mac_flat` analyzer 统一冒号、中划线、点号、无分隔格式
- 行号由应用层用 MAC 规范化后计算

验证结果：

- 输入 `4a:a9:59:4b:b6:2f`
- 命中 `cfg-001` 第 4 行：中划线格式
- 命中 `cfg-003` 第 3 行：点号格式
- 有高亮

### 5.5 普通文本模糊/包含搜索

报文：

- `opensearch/search-requests/structured-fuzzy-text.json`
- `opensearch/search-requests/config-fuzzy-text.json`

策略：

- 精确词组优先用 `match_phrase`
- 普通文本容错可用 `match` + `fuzziness`
- 任意片段兜底用 `wildcard` 或 `ngram` 子字段

建议：

- 生产默认路径不要对几十 KB 配置无限制使用 `*xxx*` 前置通配。
- 给 wildcard 查询设置超时、分页上限、字段白名单。
- IP/MAC 的“模糊”建议区分为“片段包含”或“格式归一”，不要使用编辑距离 fuzziness，否则容易产生网络标识误命中。

## 6. 行号方案

OpenSearch highlighter 返回的是片段，不返回原始文件第几行。对于 `config` 字段，推荐在应用层处理：

1. 查询命中后取 `_source.config`。
2. `splitlines()` 得到行数组。
3. 根据输入类型选择查行规则：
   - IP：使用带边界的正则，例如 `(?<![0-9A-Fa-f:.])10\.10\.10\.1(?![0-9A-Fa-f:.])`。
   - MAC：把输入和每一行都去掉 `:.-` 并小写后包含匹配。
   - 普通文本：大小写不敏感包含或业务分词匹配。
4. 返回行号、行文本、OpenSearch 高亮片段。

如果必须由 OpenSearch 直接返回行号，有两个代价更高的方案：

- 把配置拆成 nested `lines`，每行含 `line_no` 与 `line_text`。
- 把每行作为单独文档写入 `device_config_lines` 索引。

这两种方案都会新增结构或索引，不符合“非结构化索引优先不新增独立字段”的首选约束。

## 7. 已知限制

- `ip` 类型适合规范 IP 查询，不适合原始字符串高亮和异常格式保留。
- 带前导 0 的 IPv4 字符串不要直接写入 `ip` 类型，应作为异常原文保留在 keyword/text 字段。
- `term` 查询不分析查询文本；对 normalized keyword 字段使用 `term` 时，客户端要预先规范化输入。
- `wildcard` 和复杂 `regexp` 对大字段、前置通配、高并发不友好，建议作为兜底能力。
- `ngram` 增加索引体积，应只加在确实需要片段搜索的字段上。
- `query_string` 面向用户输入时必须严格转义 `:`, `.`, `-`, `*`, `?`, `(`, `)` 等特殊字符。
- 对非结构化 `config` 只增加 `config.mac` 子字段时，MAC 跨格式匹配会把任意 12 位十六进制串也视为候选。例如 `serial-number 4aa9594bb62f` 会命中输入 `4a:a9:59:4b:b6:2f`。如果业务必须排除这类干扰，需要在写入阶段抽取带 MAC 语义上下文的独立字段，或把配置拆成行级结构并保存行号、行类型、抽取出的 IP/MAC。
- MAC/IP 片段搜索天然会扩大召回，例如输入 `59` 可能命中时间 `2026-05-23 12:59:06`、端口 `Ethernet1/0/59`、`vlan 59`、版本 `4.9.59`。这类输入应明确作为“模糊/片段搜索”，不能和精确 MAC/IP 搜索共用同一套判定。

## 8. 验证命令

```bash
python3 scripts/setup_demo.py
python3 scripts/verify_search.py
```

验证报告：

```text
outputs/verification-report.json
```

当前报告证明：

- OpenSearch 版本为 2.19.3。
- IPv4 精确搜索不误命中相邻 IP。
- MAC 跨格式精确搜索可命中冒号、中划线、点号、无分隔存储。
- 结构化与非结构化索引均可高亮。
- 配置文本可输出匹配行号。
