# 业务搜索接口设计文档

## 1. 目标

封装一个后端 REST 搜索接口：

```text
POST /api/v1/business-search
```

调用方只传搜索内容和搜索模式，后端负责：

- 识别输入类型。
- 选择固定索引和字段白名单。
- 生成 OpenSearch DSL。
- 合并结构化索引和配置/长文本索引结果。
- 返回高亮、命中文本和可解析的行号。

接口支持两种搜索模式：

| 模式 | 说明 |
|---|---|
| `exact` | 业务精确模式，按输入识别为 `ip`、`mac`、`other` |
| `fuzzy` | 业务模糊/片段模式，统一按片段召回处理 |

默认搜索范围固定为后端白名单：

- 结构化索引：`structured-devices-v1`
- 配置/长文本索引：`device-configs-v1`

关键业务口径：

- IP 输入 `1.1.1.1`、`1.1.1.1/24`、`1.1.1.1/255.255.255.0` 都等同于按 host `1.1.1.1` 搜索。
- MAC 不归一化为无连接符格式，也不解析为 6 个 octet；只在冒号和横线两种格式之间生成跨格式查询值。
- MAC 精确模式使用 `wildcard` 子串匹配。
- 只有多行 text 入库时每行行首带行号；少量内容的 text 可以没有行号，接口必须兼容无行号结果。

## 2. Public API

### 2.1 Request

```json
{
  "keyword": "41:05:41:05:41:05",
  "mode": "exact",
  "from": 0,
  "size": 20
}
```

字段规则：

| 字段 | 类型 | 必填 | 规则 |
|---|---|---:|---|
| `keyword` | string | 是 | trim 后长度 2-128；用户输入中的 `* ? \\` 按普通字符转义 |
| `mode` | enum | 是 | `exact` 或 `fuzzy` |
| `from` | integer | 否 | 默认 0，最大 500 |
| `size` | integer | 否 | 默认 20，最大 100 |

接口不允许调用方传 OpenSearch DSL、索引名或字段名。所有查询字段都由后端白名单控制。

### 2.2 Response

```json
{
  "request_id": "uuid",
  "input": {
    "raw": "41:05:41:05:41:05",
    "mode": "exact",
    "detected_type": "mac",
    "search_values": [
      "41:05:41:05:41:05",
      "41-05-41-05-41-05"
    ]
  },
  "page": {
    "from": 0,
    "size": 20,
    "total": 2
  },
  "hits": [
    {
      "index": "device-configs-v1",
      "id": "cfg-001",
      "score": 8.1,
      "doc_type": "device_config",
      "source": {},
      "matched": [
        {
          "field": "config.wild",
          "match_type": "exact_mac_substring",
          "value": "L4: mac-address 41-05-41-05-41-05",
          "highlight": [
            "L4: mac-address <em>41-05-41-05-41-05</em>"
          ]
        }
      ],
      "text_hits": [
        {
          "field": "config",
          "line_no": 4,
          "line_text": "mac-address 41-05-41-05-41-05",
          "raw_text": "L4: mac-address 41-05-41-05-41-05",
          "has_line_no": true
        }
      ],
      "warnings": []
    }
  ],
  "warnings": []
}
```

无行号的少量 text 命中示例：

```json
{
  "field": "description",
  "line_no": null,
  "line_text": null,
  "raw_text": "uplink mac 41-05-41-05-41-05",
  "has_line_no": false
}
```

### 2.3 错误码

| HTTP | code | 场景 |
|---:|---|---|
| 400 | `INVALID_ARGUMENT` | 空 keyword、非法 mode、分页超限 |
| 400 | `INVALID_IP_FORMAT` | 输入像 IP/CIDR/IP+mask，但 host 或 mask 不合法 |
| 400 | `INVALID_MAC_FORMAT` | 输入像 MAC，但不是冒号或横线分隔格式 |
| 422 | `UNSUPPORTED_QUERY` | 当前输入无法生成安全查询 |
| 504 | `SEARCH_TIMEOUT` | OpenSearch 查询超时 |

## 3. Search Semantics

### 3.1 输入识别

`exact` 模式按顺序识别。

`ip` 输入：

- 接受 `1.1.1.1`
- 接受 `1.1.1.1/24`
- 接受 `1.1.1.1/255.255.255.0`
- 统一搜索 host 部分 `1.1.1.1`
- `/24` 和 `/255.255.255.0` 不表示网段查询

`mac` 输入：

- 接受 `41:05:41:05:41:05`
- 接受 `41-05-41-05-41-05`
- 大小写不敏感
- 后端只生成两个跨格式值：冒号格式和横线格式
- 不生成点号格式，不生成无连接符格式，不使用 MAC 归一化字段作为主路径

`other` 输入：

- 其他输入都视为普通文本
- `exact + other` 表示“不分词的原始片段匹配”，不是整字段相等

`fuzzy` 模式统一按片段召回处理，即使输入像 IP/MAC，也不套用精确 IP/MAC 语义。

### 3.2 分页与合并

后端使用 `_msearch` 分别查询结构化索引和配置/长文本索引，然后按 `_score desc` 合并分页。

每个索引查询：

```text
size = from + size
```

合并后再做全局 slice。`from + size` 必须小于等于 500。

## 4. DSL 生成

### 4.1 exact + ip

结构化索引：

```json
{
  "bool": {
    "should": [
      {
        "term": {
          "ip_address": {
            "value": "1.1.1.1",
            "boost": 10
          }
        }
      },
      {
        "term": {
          "ip_keyword": {
            "value": "1.1.1.1",
            "boost": 8
          }
        }
      },
      {
        "match_phrase": {
          "ip_keyword.text": {
            "query": "1.1.1.1",
            "boost": 5
          }
        }
      },
      {
        "match_phrase": {
          "attributes.text": {
            "query": "1.1.1.1",
            "boost": 4
          }
        }
      },
      {
        "match_phrase": {
          "description": {
            "query": "1.1.1.1",
            "boost": 4
          }
        }
      }
    ],
    "minimum_should_match": 1
  }
}
```

配置/长文本索引：

```json
{
  "match_phrase": {
    "config": "1.1.1.1"
  }
}
```

### 4.2 exact + mac

输入 `41:05:41:05:41:05` 生成：

```json
[
  "41:05:41:05:41:05",
  "41-05-41-05-41-05"
]
```

输入 `41-05-41-05-41-05` 也生成同样两个值。

结构化索引只在支持原文片段的字段上做 wildcard：

```json
{
  "bool": {
    "should": [
      {
        "wildcard": {
          "mac.wild": {
            "value": "*41:05:41:05:41:05*",
            "case_insensitive": true,
            "boost": 8
          }
        }
      },
      {
        "wildcard": {
          "mac.wild": {
            "value": "*41-05-41-05-41-05*",
            "case_insensitive": true,
            "boost": 8
          }
        }
      },
      {
        "wildcard": {
          "attributes.wild": {
            "value": "*41:05:41:05:41:05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      },
      {
        "wildcard": {
          "attributes.wild": {
            "value": "*41-05-41-05-41-05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      },
      {
        "wildcard": {
          "description.wild": {
            "value": "*41:05:41:05:41:05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      },
      {
        "wildcard": {
          "description.wild": {
            "value": "*41-05-41-05-41-05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      }
    ],
    "minimum_should_match": 1
  }
}
```

配置/长文本索引：

```json
{
  "bool": {
    "should": [
      {
        "wildcard": {
          "config.wild": {
            "value": "*41:05:41:05:41:05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      },
      {
        "wildcard": {
          "config.wild": {
            "value": "*41-05-41-05-41-05*",
            "case_insensitive": true,
            "boost": 5
          }
        }
      }
    ],
    "minimum_should_match": 1
  }
}
```

### 4.3 exact + other

结构化索引：

```json
{
  "bool": {
    "should": [
      {
        "wildcard": {
          "name.wild": {
            "value": "*admin*",
            "case_insensitive": true,
            "boost": 4
          }
        }
      },
      {
        "wildcard": {
          "vendor.wild": {
            "value": "*admin*",
            "case_insensitive": true,
            "boost": 3
          }
        }
      },
      {
        "wildcard": {
          "attributes.wild": {
            "value": "*admin*",
            "case_insensitive": true,
            "boost": 3
          }
        }
      },
      {
        "wildcard": {
          "description.wild": {
            "value": "*admin*",
            "case_insensitive": true,
            "boost": 3
          }
        }
      }
    ],
    "minimum_should_match": 1
  }
}
```

配置/长文本索引：

```json
{
  "wildcard": {
    "config.wild": {
      "value": "*admin*",
      "case_insensitive": true
    }
  }
}
```

`exact + other` 不使用 `match`，避免分词后扩大语义。

### 4.4 fuzzy

模糊模式统一为片段召回：

- 结构化索引查 `.wild` 和 `.ngram` 子字段。
- 配置/长文本索引查 `config.wild`、`config.ngram`，可以附加 `match_phrase config` 提升高亮稳定性。
- 不默认使用 `match + fuzziness`。
- 不对 IP/MAC 使用编辑距离模糊。

示例：

```json
{
  "bool": {
    "should": [
      {
        "wildcard": {
          "config.wild": {
            "value": "*gatew*",
            "case_insensitive": true,
            "boost": 3
          }
        }
      },
      {
        "match": {
          "config.ngram": {
            "query": "gatew",
            "boost": 2
          }
        }
      },
      {
        "match_phrase": {
          "config": {
            "query": "gatew",
            "boost": 1
          }
        }
      }
    ],
    "minimum_should_match": 1
  }
}
```

## 5. Result Enrichment

### 5.1 高亮

所有查询默认返回高亮。

结构化索引高亮字段：

- `ip_keyword`
- `attributes.text`
- `description`
- `mac`
- `mac.wild`
- `attributes.wild`
- `description.wild`
- `name`
- `vendor.text`

配置/长文本索引高亮字段：

- `config`
- `config.wild`

如果 wildcard 查询未返回高亮，响应仍返回命中文档，并在 hit 的 `warnings` 中加入 `HIGHLIGHT_NOT_AVAILABLE`。

### 5.2 Text 命中与行号兼容

接口统一返回 `text_hits`，兼容有行号和无行号两种 text。

多行 text 入库格式：

```text
L3: ip address 1.1.1.1 255.255.255.0
L4: mac-address 41-05-41-05-41-05
```

解析规则：

- 如果命中行匹配 `^L(?<line_no>\\d+):\\s?(?<line_text>.*)$`，返回 `has_line_no=true`、`line_no` 和去掉前缀的 `line_text`。
- 如果命中文本不带行号前缀，返回 `has_line_no=false`、`line_no=null`、`line_text=null`、`raw_text` 为实际命中文本。
- 对短文本字段，例如 `description`、`name`、`vendor.text`，默认视为无行号 text，不强行解析行号。
- 对多行 text，如果某一行未带 `L{line_no}:` 前缀，也按无行号命中处理，并在该 hit 的 `warnings` 中加入 `LINE_NO_NOT_AVAILABLE`。

命中文本判断：

| 输入类型 | 判断方式 |
|---|---|
| `ip` | 文本包含 host IP，并用 IP 边界避免相邻 IP |
| `mac` | 文本包含冒号格式或横线格式任一查询值 |
| `other` | 文本大小写不敏感包含原始片段 |
| `fuzzy` | 文本大小写不敏感包含原始片段；无法定位时返回空 `text_hits` |

## 6. Safety Limits

- 不暴露 `query_string`。
- 用户输入中的 `*`、`?`、`\` 必须转义，不能作为 wildcard 语法透传。
- wildcard 只允许查询后端白名单字段。
- 单次 OpenSearch timeout 设为 2s。
- `from + size <= 500`。
- `keyword` 最小长度为 2。
- MAC 精确模式最多生成 2 个查询值：冒号格式和横线格式。
- MAC wildcard 是子串匹配，可能命中包含同样字符串的非 MAC 文本；响应通过 `match_type=exact_mac_substring` 明确语义，不伪装为结构化 MAC 等值匹配。

## 7. Test Plan

核心验收用例：

1. `exact + ip`
   - `1.1.1.1`、`1.1.1.1/24`、`1.1.1.1/255.255.255.0` 都等价搜索 `1.1.1.1`。
   - 不命中 `1.1.1.10`、`11.1.1.1`、`1.1.1.100`。
2. `exact + mac`
   - 输入 `41:05:41:05:41:05` 只生成 `41:05:41:05:41:05` 和 `41-05-41-05-41-05`。
   - 输入 `41-05-41-05-41-05` 生成同样两个查询值。
   - 能跨冒号/横线格式命中。
   - 不生成 `4105.4105.4105`，不生成 `410541054105`。
   - DSL 使用 wildcard 子串匹配，不使用 `mac_norm` 或 `config.mac` 作为主路径。
3. `exact + other`
   - 输入 `admin` 使用 wildcard 原文片段匹配。
   - 能命中 `allow-admin`，响应 `match_type=contains_literal`。
4. `fuzzy`
   - 输入 `gatew` 能通过 `.wild` 或 `.ngram` 命中 `gateway`。
   - 输入 `59` 允许扩大召回，响应保留实际命中内容。
5. Text 行号兼容
   - 入库文本行 `L4: mac-address 41-05-41-05-41-05` 命中后返回 `has_line_no=true`、`line_no=4`。
   - 短文本 `uplink mac 41-05-41-05-41-05` 命中后返回 `has_line_no=false`、`line_no=null`。
   - 多行 text 中某一行没有行号前缀时，不报错，返回无行号命中并给 `LINE_NO_NOT_AVAILABLE` warning。
6. 防误用
   - 空 keyword、长度 1、非法 mode、分页超限返回 400。
   - 用户输入 `*admin*` 按字面量搜索，不作为 wildcard 语法执行。

## 8. Assumptions

- 本设计只定义 REST API；内部 service 可复用相同请求/响应模型。
- 接口默认搜索后端预设范围，不允许调用方指定索引和字段。
- 高亮和 text 命中明细是标准响应能力，不做请求开关。
- `exact + other` 的“精确”按业务定义解释为“不分词的原始片段匹配”。
- `1.1.1.1/24` 和 `1.1.1.1/255.255.255.0` 只等同搜索 host，不做网段搜索。
- MAC v1 只支持冒号和横线两种输入/跨格式匹配；点号和无连接符格式不在本轮设计范围内。
- 多行 text 行号前缀统一为 `L{line_no}: `；少量内容 text 可以没有行号，接口必须正常返回无行号命中。
