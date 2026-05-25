#!/usr/bin/env python3
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")
OUTPUT = ROOT / "outputs" / "search-matrix-results.json"
VERIFY_OUTPUT = ROOT / "outputs" / "verification-report.json"

SEARCH_MODES = [
    "term",
    "match",
    "match_phrase",
    "wildcard",
    "regexp",
    "match_fuzzy",
    "query_string",
]

FIELD_SPECS = [
    {"index": "structured-devices-v1", "field": "ip_address", "source_field": "ip_address", "field_type": "ip", "stored_shape": "纯 IPv4/IPv6"},
    {"index": "structured-devices-v1", "field": "ip_keyword", "source_field": "ip_keyword", "field_type": "keyword", "stored_shape": "纯 IP keyword"},
    {"index": "structured-devices-v1", "field": "ip_keyword.text", "source_field": "ip_keyword", "field_type": "text", "stored_shape": "纯 IP keyword 的 text 子字段"},
    {"index": "structured-devices-v1", "field": "ip_keyword.wild", "source_field": "ip_keyword", "field_type": "wildcard", "stored_shape": "纯 IP keyword 的 wildcard 子字段"},
    {"index": "structured-devices-v1", "field": "ip_keyword.ngram", "source_field": "ip_keyword", "field_type": "text", "stored_shape": "纯 IP keyword 的 ngram 子字段"},
    {"index": "structured-devices-v1", "field": "mac", "source_field": "mac", "field_type": "keyword", "stored_shape": "纯 MAC keyword，含冒号/中划线/点号/无分隔"},
    {"index": "structured-devices-v1", "field": "mac.mac", "source_field": "mac", "field_type": "text", "stored_shape": "纯 MAC 的 mac_flat 子字段"},
    {"index": "structured-devices-v1", "field": "mac.wild", "source_field": "mac", "field_type": "wildcard", "stored_shape": "纯 MAC 的 wildcard 子字段"},
    {"index": "structured-devices-v1", "field": "attributes", "source_field": "attributes", "field_type": "keyword", "stored_shape": "包含 IP/MAC/普通文本的 keyword"},
    {"index": "structured-devices-v1", "field": "attributes.text", "source_field": "attributes", "field_type": "text", "stored_shape": "包含 IP/MAC/普通文本的 text 子字段"},
    {"index": "structured-devices-v1", "field": "attributes.mac", "source_field": "attributes", "field_type": "text", "stored_shape": "包含 MAC 的 mac_flat 子字段"},
    {"index": "structured-devices-v1", "field": "attributes.wild", "source_field": "attributes", "field_type": "wildcard", "stored_shape": "包含 IP/MAC/普通文本的 wildcard 子字段"},
    {"index": "structured-devices-v1", "field": "attributes.ngram", "source_field": "attributes", "field_type": "text", "stored_shape": "包含 IP/MAC/普通文本的 ngram 子字段"},
    {"index": "structured-devices-v1", "field": "description", "source_field": "description", "field_type": "text", "stored_shape": "包含 IP/MAC/普通文本的 text"},
    {"index": "structured-devices-v1", "field": "description.mac", "source_field": "description", "field_type": "text", "stored_shape": "description 的 mac_flat 子字段"},
    {"index": "structured-devices-v1", "field": "description.wild", "source_field": "description", "field_type": "wildcard", "stored_shape": "description 的 wildcard 子字段"},
    {"index": "structured-devices-v1", "field": "description.ngram", "source_field": "description", "field_type": "text", "stored_shape": "description 的 ngram 子字段"},
    {"index": "device-configs-v1", "field": "config", "source_field": "config", "field_type": "text", "stored_shape": "多行配置 text，包含 IP/MAC/时间/命令"},
    {"index": "device-configs-v1", "field": "config.mac", "source_field": "config", "field_type": "text", "stored_shape": "多行配置的 mac_flat 子字段"},
    {"index": "device-configs-v1", "field": "config.wild", "source_field": "config", "field_type": "wildcard", "stored_shape": "多行配置的 wildcard 子字段"},
    {"index": "device-configs-v1", "field": "config.ngram", "source_field": "config", "field_type": "text", "stored_shape": "多行配置的 ngram 子字段"},
]

INPUTS = [
    {"id": "ipv4_exact", "value": "10.10.10.1", "input_type": "纯 IPv4", "semantic": "exact_ip"},
    {"id": "ipv6_exact", "value": "2001:db8::1", "input_type": "纯 IPv6", "semantic": "exact_ip"},
    {"id": "ipv4_leading_zero", "value": "010.010.010.001", "input_type": "前导 0 IPv4", "semantic": "exact_ip"},
    {"id": "mac_cross_4a", "value": "4a:a9:59:4b:b6:2f", "input_type": "纯 MAC", "semantic": "exact_mac"},
    {"id": "mac_cross_00", "value": "00:11:22:33:44:55", "input_type": "纯 MAC", "semantic": "exact_mac"},
    {"id": "text_gateway", "value": "gateway", "input_type": "普通文本", "semantic": "text"},
    {"id": "text_allow_admin", "value": "allow-admin", "input_type": "普通文本", "semantic": "text"},
    {"id": "partial_ip", "value": "10.10.10", "input_type": "片段/模糊 IP", "semantic": "partial"},
    {"id": "partial_mac", "value": "4a:a9", "input_type": "片段/模糊 MAC", "semantic": "partial_mac"},
    {"id": "partial_mac_octet_59", "value": "59", "input_type": "MAC 片段/高干扰数值", "semantic": "partial_mac"},
    {"id": "partial_time_06", "value": "06", "input_type": "MAC/时间片段高干扰数值", "semantic": "partial"},
    {"id": "partial_admin", "value": "admin", "input_type": "片段/普通文本", "semantic": "partial"},
    {"id": "partial_gatew", "value": "gatew", "input_type": "片段/普通文本", "semantic": "partial"},
]

RECOMMENDED_CASES = [
    {
        "case_id": "rec_structured_ipv4_exact",
        "index": "structured-devices-v1",
        "field": "推荐组合(结构化)",
        "field_type": "combined",
        "stored_shape": "ip/keyword/text/wildcard 多字段组合",
        "source_field": "ip_keyword",
        "input": INPUTS[0],
        "expected_ids": ["dev-001"],
        "expected_exclude_ids": ["dev-002"],
        "line_required": False,
    },
    {
        "case_id": "rec_structured_mac_cross",
        "index": "structured-devices-v1",
        "field": "推荐组合(结构化)",
        "field_type": "combined",
        "stored_shape": "keyword normalizer + mac_flat 多字段组合",
        "source_field": "mac",
        "input": INPUTS[3],
        "expected_ids": ["dev-001", "dev-003"],
        "expected_exclude_ids": [],
        "line_required": False,
    },
    {
        "case_id": "rec_config_ipv4_exact",
        "index": "device-configs-v1",
        "field": "推荐组合(config)",
        "field_type": "combined",
        "stored_shape": "config text + 应用层行号",
        "source_field": "config",
        "input": INPUTS[0],
        "expected_ids": ["cfg-001", "cfg-003"],
        "expected_exclude_ids": ["cfg-002"],
        "line_required": True,
    },
    {
        "case_id": "rec_config_mac_cross",
        "index": "device-configs-v1",
        "field": "推荐组合(config)",
        "field_type": "combined",
        "stored_shape": "config.mac + 应用层行号",
        "source_field": "config",
        "input": INPUTS[3],
        "expected_ids": ["cfg-001", "cfg-003"],
        "expected_exclude_ids": [],
        "line_required": True,
    },
    {
        "case_id": "rec_config_text_fuzzy",
        "index": "device-configs-v1",
        "field": "推荐组合(config)",
        "field_type": "combined",
        "stored_shape": "match_phrase + ngram + wildcard",
        "source_field": "config",
        "input": INPUTS[6],
        "expected_ids": ["cfg-003"],
        "expected_exclude_ids": [],
        "line_required": True,
    },
]


def request(method, path, body=None, expected=(200,)):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


def get_json(path):
    status, payload = request("GET", path)
    if status >= 400:
        raise RuntimeError(f"GET {path} failed: {payload}")
    return payload


def post_search(index, body):
    return request("POST", f"/{index}/_search", body)


def norm_mac(value):
    return re.sub(r"[:.\-\s]", "", str(value)).lower()


def ip_boundary_match(text, query):
    pattern = re.compile(rf"(?<![0-9A-Fa-f:.]){re.escape(query)}(?![0-9A-Fa-f:.])", re.I)
    return bool(pattern.search(str(text)))


def text_contains(text, query):
    return str(query).lower() in str(text).lower()


def mac_parts(value):
    compact = norm_mac(value)
    return [compact[i:i + 2] for i in range(0, len(compact), 2) if len(compact[i:i + 2]) == 2]


def has_mac_context(text, query):
    lowered = str(text).lower()
    compact = norm_mac(query)
    if "mac" in lowered and compact in norm_mac(text):
        return True
    if re.search(r"(?i)(mac-address|mac addr|mac=|mac )", lowered):
        return True
    return False


def intended_value_match(text, query, semantic, source_field=""):
    value = str(text)
    if semantic == "exact_ip":
        return ip_boundary_match(value, query)
    if semantic == "exact_mac":
        compact = norm_mac(query)
        if len(compact) != 12 or compact not in norm_mac(value):
            return False
        return source_field == "mac" or has_mac_context(value, query)
    if semantic == "partial_mac":
        compact = norm_mac(query)
        if not compact or compact not in norm_mac(value):
            return False
        return source_field == "mac" or has_mac_context(value, query)
    return text_contains(value, query)


def candidate_line_hits(config, query, semantic):
    hits = []
    compact_query = norm_mac(query)
    parts = set(mac_parts(query))
    for no, line in enumerate(str(config).splitlines(), 1):
        matched = False
        reason = ""
        if intended_value_match(line, query, semantic, "config"):
            matched = True
            reason = "符合输入本意"
        elif semantic == "exact_ip" and text_contains(line, query):
            matched = True
            reason = "IP 字符串包含但边界不符合精确意图"
        elif semantic == "exact_mac":
            line_norm = norm_mac(line)
            shared = sorted(part for part in parts if part and part in line_norm)
            if compact_query and compact_query in line_norm:
                matched = True
                reason = "完整 12 位 hex 出现但缺少 MAC 语义上下文"
            elif shared:
                matched = True
                reason = "仅 MAC 片段重合: " + ",".join(shared[:4])
        elif semantic == "partial_mac":
            if compact_query and compact_query in norm_mac(line):
                matched = True
                reason = "片段匹配，可能来自时间/端口/版本/普通 hex"
        elif text_contains(line, query):
            matched = True
            reason = "文本包含"
        if matched:
            hits.append({
                "line": no,
                "text": line,
                "is_intended": intended_value_match(line, query, semantic, "config"),
                "reason": reason,
            })
    return hits


def line_hits(config, query, semantic):
    hits = []
    lines = str(config).splitlines()
    if semantic == "exact_ip":
        for no, line in enumerate(lines, 1):
            if ip_boundary_match(line, query):
                hits.append({"line": no, "text": line})
    elif semantic in {"exact_mac", "partial_mac"}:
        q = norm_mac(query)
        for no, line in enumerate(lines, 1):
            if q and q in norm_mac(line):
                hits.append({"line": no, "text": line})
    else:
        for no, line in enumerate(lines, 1):
            if text_contains(line, query):
                hits.append({"line": no, "text": line})
    return hits


def load_mock_docs():
    data_path = ROOT / "data" / "mock-documents.json"
    if not data_path.exists():
        raise RuntimeError("data/mock-documents.json is missing; run scripts/setup_demo.py first")
    return json.loads(data_path.read_text(encoding="utf-8"))


def source_docs(mock, index):
    return mock[index]


def doc_id(doc):
    return doc["_id"]


def source_value(doc, field):
    return doc.get(field)


def expected_ids_for(mock, spec, input_def):
    ids = []
    query = input_def["value"]
    semantic = input_def["semantic"]
    for doc in source_docs(mock, spec["index"]):
        value = source_value(doc, spec["source_field"])
        if value is None:
            continue
        matched = intended_value_match(value, query, semantic, spec["source_field"])
        if matched:
            ids.append(doc_id(doc))
    return sorted(ids)


def escape_query_string(value):
    specials = r'+-=&|><!(){}[]^"~*?:\/'
    return "".join(f"\\{ch}" if ch in specials else ch for ch in str(value))


def regexp_literal_contains(value):
    escaped = ""
    for ch in str(value):
        if ch in r'.?+*|{}[]()"\#@&<>~':
            escaped += "\\" + ch
        else:
            escaped += ch
    return f".*{escaped}.*"


def highlight_for(field):
    return {
        "require_field_match": False,
        "fields": {
            field: {
                "type": "unified",
                "force_source": True,
                "number_of_fragments": 5,
            }
        },
    }


def query_body(field, mode, query):
    base = {"size": 20, "_source": True, "highlight": highlight_for(field)}
    if mode == "term":
        base["query"] = {"term": {field: query}}
    elif mode == "match":
        base["query"] = {"match": {field: query}}
    elif mode == "match_phrase":
        base["query"] = {"match_phrase": {field: query}}
    elif mode == "wildcard":
        base["query"] = {"wildcard": {field: {"value": f"*{query}*", "case_insensitive": True}}}
    elif mode == "regexp":
        base["query"] = {"regexp": {field: {"value": regexp_literal_contains(query), "case_insensitive": True}}}
    elif mode == "match_fuzzy":
        base["query"] = {"match": {field: {"query": query, "fuzziness": "AUTO"}}}
    elif mode == "query_string":
        if query in {"10.10.10", "4a:a9", "59", "06", "admin", "gatew"}:
            q = f"*{escape_query_string(query)}*"
        else:
            q = f"\"{escape_query_string(query)}\""
        base["query"] = {"query_string": {"fields": [field], "query": q}}
    else:
        raise ValueError(f"unknown mode {mode}")
    return base


def recommended_query_body(case):
    query = case["input"]["value"]
    if case["case_id"] == "rec_structured_ipv4_exact":
        return {
            "size": 20,
            "_source": True,
            "query": {
                "bool": {
                    "should": [
                        {"term": {"ip_address": query}},
                        {"term": {"ip_keyword": query}},
                        {"match_phrase": {"ip_keyword.text": query}},
                        {"match_phrase": {"attributes.text": query}},
                        {"match_phrase": {"description": query}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "highlight": {
                "require_field_match": False,
                "fields": {
                    "ip_keyword": {"type": "unified", "force_source": True},
                    "attributes.text": {"type": "unified", "force_source": True},
                    "description": {"type": "unified"},
                },
            },
        }
    if case["case_id"] == "rec_structured_mac_cross":
        return {
            "size": 20,
            "_source": True,
            "query": {
                "bool": {
                    "should": [
                        {"match": {"mac": query}},
                        {"match": {"mac.mac": query}},
                        {"match": {"attributes.mac": query}},
                        {"match": {"description.mac": query}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "highlight": {
                "require_field_match": False,
                "fields": {
                    "mac": {"type": "unified", "force_source": True},
                    "attributes.mac": {"type": "unified", "force_source": True},
                    "description": {"type": "unified"},
                },
            },
        }
    if case["case_id"] == "rec_config_ipv4_exact":
        return {
            "size": 20,
            "_source": True,
            "query": {"match_phrase": {"config": query}},
            "highlight": {"fields": {"config": {"type": "unified", "number_of_fragments": 5}}},
        }
    if case["case_id"] == "rec_config_mac_cross":
        return {
            "size": 20,
            "_source": True,
            "query": {"match": {"config.mac": query}},
            "highlight": {
                "require_field_match": False,
                "fields": {
                    "config": {"type": "unified", "number_of_fragments": 5},
                    "config.mac": {"type": "unified", "number_of_fragments": 5},
                },
            },
        }
    if case["case_id"] == "rec_config_text_fuzzy":
        return {
            "size": 20,
            "_source": True,
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"config": query}},
                        {"match": {"config.ngram": query}},
                        {"wildcard": {"config.wild": {"value": f"*{query.lower()}*", "case_insensitive": True}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "highlight": {"fields": {"config": {"type": "unified", "number_of_fragments": 5}}},
        }
    raise ValueError(case["case_id"])


def summarize_dsl(body):
    query = body.get("query", {})
    if "term" in query:
        field = next(iter(query["term"]))
        return f"term {field}"
    if "match" in query:
        field = next(iter(query["match"]))
        return f"match {field}"
    if "match_phrase" in query:
        field = next(iter(query["match_phrase"]))
        return f"match_phrase {field}"
    if "wildcard" in query:
        field = next(iter(query["wildcard"]))
        return f"wildcard {field} *input*"
    if "regexp" in query:
        field = next(iter(query["regexp"]))
        return f"regexp {field} .*input.*"
    if "query_string" in query:
        return "query_string fields=" + ",".join(query["query_string"].get("fields", []))
    if "bool" in query:
        return "bool should 推荐组合"
    return json.dumps(query, ensure_ascii=False)[:200]


def build_case_id(spec, input_def, mode):
    field = spec["field"].replace(".", "_").replace("(", "").replace(")", "")
    return f"{spec['index']}_{field}_{input_def['id']}_{mode}"


def flatten_highlights(hit):
    fragments = []
    for values in (hit.get("highlight") or {}).values():
        fragments.extend(values)
    return fragments


def build_hit_details(index, hits, source_field, query, semantic, expected_ids):
    expected = set(expected_ids)
    details = []
    for hit in hits:
        hit_id = hit["_id"]
        source = hit.get("_source", {})
        highlights = flatten_highlights(hit)
        if index == "device-configs-v1":
            line_candidates = candidate_line_hits(source.get("config", ""), query, semantic)
            intended_lines = [line for line in line_candidates if line["is_intended"]]
            interference_lines = [line for line in line_candidates if not line["is_intended"]]
            is_intended = hit_id in expected and bool(intended_lines or not line_candidates)
            reason = "" if is_intended and not interference_lines else "命中文档中存在偏离搜索本意的配置行"
            if hit_id not in expected:
                reason = "命中文档不在按搜索本意计算的预期集合中"
            details.append({
                "doc_id": hit_id,
                "field_value": "",
                "matched_lines": line_candidates,
                "highlight_fragments": highlights,
                "is_intended": is_intended,
                "interference_reason": reason,
            })
        else:
            value = source.get(source_field, "")
            is_intended = hit_id in expected and intended_value_match(value, query, semantic, source_field)
            reason = ""
            if not is_intended:
                if semantic in {"exact_mac", "partial_mac"}:
                    reason = "命中值包含 MAC 片段或 12 位 hex，但不是明确 MAC 语义"
                elif semantic == "exact_ip":
                    reason = "命中值包含 IP 字符串片段，但不符合精确 IP 边界"
                else:
                    reason = "命中值偏离该输入的主要搜索本意"
            details.append({
                "doc_id": hit_id,
                "field_value": str(value),
                "matched_lines": [],
                "highlight_fragments": highlights,
                "is_intended": is_intended,
                "interference_reason": reason,
            })
    return details


def actual_from_response(index, payload, query, semantic, source_field, expected_ids):
    hits = payload.get("hits", {}).get("hits", [])
    actual_ids = [hit["_id"] for hit in hits]
    highlight_ids = [hit["_id"] for hit in hits if hit.get("highlight")]
    config_line_hits = {}
    if index == "device-configs-v1":
        for hit in hits:
            config = hit.get("_source", {}).get("config", "")
            lines = line_hits(config, query, semantic)
            if lines:
                config_line_hits[hit["_id"]] = lines
    hit_details = build_hit_details(index, hits, source_field, query, semantic, expected_ids)
    interference_hit_details = []
    for detail in hit_details:
        if not detail["is_intended"]:
            interference_hit_details.append(detail)
            continue
        bad_lines = [line for line in detail.get("matched_lines", []) if not line.get("is_intended")]
        if bad_lines:
            clone = dict(detail)
            clone["matched_lines"] = bad_lines
            clone["interference_reason"] = "同一命中文档中有额外干扰行"
            interference_hit_details.append(clone)
    return actual_ids, highlight_ids, config_line_hits, hit_details, interference_hit_details


def verdict_and_rating(mode, expected_ids, actual_ids, unexpected_ids, missing_ids, error, has_highlight, line_required, line_hits_map, interference_hit_details=None):
    interference_hit_details = interference_hit_details or []
    if error:
        return "执行错误/不适用", "不可用"
    if not expected_ids and not actual_ids:
        return "当前字段和输入无相关测试数据，实际无命中", "不适用"
    notes = []
    if unexpected_ids:
        notes.append("误命中 " + ",".join(unexpected_ids))
    if missing_ids:
        notes.append("漏命中 " + ",".join(missing_ids))
    if interference_hit_details:
        notes.append("存在干扰命中 " + ",".join(item["doc_id"] for item in interference_hit_details[:5]))
    if actual_ids and not has_highlight:
        notes.append("有命中但无高亮")
    if line_required and actual_ids:
        ids_without_lines = [doc_id for doc_id in actual_ids if doc_id not in line_hits_map]
        if ids_without_lines:
            notes.append("缺少行号 " + ",".join(ids_without_lines))
    if notes:
        rating = "不推荐" if unexpected_ids or missing_ids or interference_hit_details else "可用但有限制"
        return "；".join(notes), rating
    if mode == "recommended_combo":
        return "推荐组合满足预期，命中/排除/高亮/行号均符合要求", "推荐"
    if mode in {"wildcard", "regexp", "query_string", "match_fuzzy"}:
        return "实测符合预期，但该搜索方式有性能或语义限制", "可用但有限制"
    return "实测符合预期", "推荐"


def load_mapping_rows():
    rows = []
    for index, file_name in {
        "structured-devices-v1": "structured-devices-v1.json",
        "device-configs-v1": "device-configs-v1.json",
    }.items():
        body = json.loads((ROOT / "opensearch" / "indices" / file_name).read_text(encoding="utf-8"))
        analysis = body.get("settings", {}).get("analysis", {})
        props = body.get("mappings", {}).get("properties", {})

        def walk(prefix, mapping):
            for name, spec in mapping.items():
                field = f"{prefix}.{name}" if prefix else name
                rows.append({
                    "index": index,
                    "field": field,
                    "type": spec.get("type", "object"),
                    "analyzer": spec.get("analyzer", ""),
                    "search_analyzer": spec.get("search_analyzer", ""),
                    "normalizer": spec.get("normalizer", ""),
                    "term_vector": spec.get("term_vector", ""),
                    "subfields": ",".join(sorted((spec.get("fields") or {}).keys())),
                })
                fields = spec.get("fields") or {}
                if fields:
                    walk(field, fields)

        walk("", props)
        for kind, values in analysis.items():
            if isinstance(values, dict):
                for name, value in values.items():
                    rows.append({
                        "index": index,
                        "field": f"analysis.{kind}.{name}",
                        "type": value.get("type", kind),
                        "analyzer": json.dumps(value, ensure_ascii=False),
                        "search_analyzer": "",
                        "normalizer": "",
                        "term_vector": "",
                        "subfields": "",
                    })
    return rows


def build_test_data_rows(mock):
    rows = []
    for spec in FIELD_SPECS:
        for doc in source_docs(mock, spec["index"]):
            value = source_value(doc, spec["source_field"])
            if value is None:
                continue
            if spec["index"] == "device-configs-v1" and spec["source_field"] == "config":
                for line_no, line in enumerate(str(value).splitlines(), 1):
                    rows.append({
                        "index": spec["index"],
                        "doc_id": doc_id(doc),
                        "field": spec["field"],
                        "field_type": spec["field_type"],
                        "source_field": spec["source_field"],
                        "stored_shape": spec["stored_shape"],
                        "line_no": line_no,
                        "stored_value": line,
                    })
            else:
                rows.append({
                    "index": spec["index"],
                    "doc_id": doc_id(doc),
                    "field": spec["field"],
                    "field_type": spec["field_type"],
                    "source_field": spec["source_field"],
                    "stored_shape": spec["stored_shape"],
                    "line_no": "",
                    "stored_value": str(value),
                })
    return rows


def run_field_case(mock, spec, input_def, mode):
    case_id = build_case_id(spec, input_def, mode)
    expected = expected_ids_for(mock, spec, input_def)
    body = query_body(spec["field"], mode, input_def["value"])
    status, payload = post_search(spec["index"], body)
    error = None
    actual_ids = []
    highlight_ids = []
    config_line_hits = {}
    hit_details = []
    interference_hit_details = []
    if status >= 400:
        error = payload.get("error", payload)
    else:
        actual_ids, highlight_ids, config_line_hits, hit_details, interference_hit_details = actual_from_response(
            spec["index"], payload, input_def["value"], input_def["semantic"], spec["source_field"], expected
        )
    actual_set = set(actual_ids)
    expected_set = set(expected)
    unexpected = sorted(actual_set - expected_set)
    missing = sorted(expected_set - actual_set)
    line_required = spec["index"] == "device-configs-v1" and bool(actual_ids)
    verdict, rating = verdict_and_rating(
        mode, expected, actual_ids, unexpected, missing, error, bool(highlight_ids), line_required, config_line_hits, interference_hit_details
    )
    return {
        "case_id": case_id,
        "index": spec["index"],
        "field": spec["field"],
        "field_type": spec["field_type"],
        "stored_shape": spec["stored_shape"],
        "source_field": spec["source_field"],
        "input_id": input_def["id"],
        "input_value": input_def["value"],
        "input_type": input_def["input_type"],
        "search_mode": mode,
        "dsl_summary": summarize_dsl(body),
        "dsl": body,
        "expected_ids": expected,
        "expected_exclude_ids": [],
        "actual_ids": actual_ids,
        "unexpected_ids": unexpected,
        "missing_ids": missing,
        "highlight_ids": highlight_ids,
        "has_highlight": bool(highlight_ids),
        "line_hits": config_line_hits,
        "hit_details": hit_details,
        "interference_hit_details": interference_hit_details,
        "line_required": line_required,
        "status": status,
        "error": error,
        "verdict": verdict,
        "recommendation": rating,
    }


def run_recommended_case(case):
    body = recommended_query_body(case)
    status, payload = post_search(case["index"], body)
    error = None
    actual_ids = []
    highlight_ids = []
    config_line_hits = {}
    hit_details = []
    interference_hit_details = []
    if status >= 400:
        error = payload.get("error", payload)
    else:
        source_field = case.get("source_field") or ("config" if case["index"] == "device-configs-v1" else "mac")
        actual_ids, highlight_ids, config_line_hits, hit_details, interference_hit_details = actual_from_response(
            case["index"], payload, case["input"]["value"], case["input"]["semantic"], source_field, case["expected_ids"]
        )
    actual_set = set(actual_ids)
    expected_set = set(case["expected_ids"])
    unexpected = sorted((actual_set - expected_set) | (actual_set & set(case["expected_exclude_ids"])))
    missing = sorted(expected_set - actual_set)
    verdict, rating = verdict_and_rating(
        "recommended_combo",
        case["expected_ids"],
        actual_ids,
        unexpected,
        missing,
        error,
        bool(highlight_ids),
        case["line_required"],
        config_line_hits,
        interference_hit_details,
    )
    return {
        "case_id": case["case_id"],
        "index": case["index"],
        "field": case["field"],
        "field_type": case["field_type"],
        "stored_shape": case["stored_shape"],
        "source_field": source_field,
        "input_id": case["input"]["id"],
        "input_value": case["input"]["value"],
        "input_type": case["input"]["input_type"],
        "search_mode": "recommended_combo",
        "dsl_summary": summarize_dsl(body),
        "dsl": body,
        "expected_ids": case["expected_ids"],
        "expected_exclude_ids": case["expected_exclude_ids"],
        "actual_ids": actual_ids,
        "unexpected_ids": unexpected,
        "missing_ids": missing,
        "highlight_ids": highlight_ids,
        "has_highlight": bool(highlight_ids),
        "line_hits": config_line_hits,
        "hit_details": hit_details,
        "interference_hit_details": interference_hit_details,
        "line_required": case["line_required"],
        "status": status,
        "error": error,
        "verdict": verdict,
        "recommendation": rating,
    }


def aggregate(cases):
    summary = {}
    for case in cases:
        key = (case["field_type"], case["input_type"], case["search_mode"])
        item = summary.setdefault(key, {"total": 0, "推荐": 0, "可用但有限制": 0, "不推荐": 0, "不可用": 0, "不适用": 0})
        item["total"] += 1
        item[case["recommendation"]] = item.get(case["recommendation"], 0) + 1
    rows = []
    for (field_type, input_type, mode), item in sorted(summary.items()):
        success = item["推荐"] + item["可用但有限制"]
        if item["推荐"]:
            overall = "推荐"
        elif item["可用但有限制"]:
            overall = "可用但有限制"
        elif item["不推荐"]:
            overall = "不推荐"
        elif item["不可用"]:
            overall = "不可用"
        else:
            overall = "不适用"
        rows.append({
            "field_type": field_type,
            "input_type": input_type,
            "search_mode": mode,
            "total": item["total"],
            "recommended": item.get("推荐", 0),
            "usable_limited": item.get("可用但有限制", 0),
            "not_recommended": item.get("不推荐", 0),
            "unavailable": item.get("不可用", 0),
            "not_applicable": item.get("不适用", 0),
            "success_rate": round(success / item["total"], 4) if item["total"] else 0,
            "overall_recommendation": overall,
        })
    return rows


def limitation_rows(cases):
    fixed = [
        ["ip 类型 + 前导 0 IPv4", "010.010.010.001 不能作为规范 IPv4 写入 ip 字段", "使用 keyword/text 原文保存，并在应用层做规范化/异常标记"],
        ["term 不分析输入", "term 直接查 text 或 normalized keyword 时容易与索引 token 不一致", "仅用于 ip/keyword 的精确值；MAC term 要先规范化输入"],
        ["wildcard 成本", "前置通配 *input* 在大字段和高并发下成本高", "只作为兜底，限制字段、输入长度、分页和超时"],
        ["ip 字段高亮弱", "ip 类型不是文本字段，不适合作为展示高亮字段", "用 keyword/text 原文字段负责高亮"],
        ["OpenSearch 不返回行号", "highlighter 返回片段，不返回 config 第几行", "应用层 splitlines 后按 IP/MAC/text 规则计算行号"],
        ["query_string 转义", "IP/MAC 中的 :, -, . 等字符容易触发 query_string 语法歧义", "后端生成 DSL，普通用户输入不要直连 query_string"],
    ]
    dynamic = []
    for case in cases:
        if case.get("interference_hit_details") and len(dynamic) < 25:
            first = case["interference_hit_details"][0]
            if first.get("matched_lines"):
                sample = "; ".join(f"L{line['line']}: {line['text']}" for line in first["matched_lines"][:2])
            else:
                sample = first.get("field_value", "")
            dynamic.append([
                f"{case['field']} + {case['input_value']} + {case['search_mode']}",
                f"干扰命中: {sample}",
                "精确 IP/MAC 走专用字段和推荐组合；片段搜索明确标识为模糊模式",
            ])
        elif case["recommendation"] in {"不推荐", "不可用"} and len(dynamic) < 50:
            dynamic.append([
                f"{case['field']} + {case['input_value']} + {case['search_mode']}",
                case["verdict"],
                "详见 03_交叉验证明细 的实际命中、误命中、漏命中和 DSL",
            ])
    return [{"scenario": a, "limitation": b, "suggestion": c} for a, b, c in fixed + dynamic]


def verification_report(version, cases):
    critical_ids = {
        "rec_structured_ipv4_exact",
        "rec_structured_mac_cross",
        "rec_config_ipv4_exact",
        "rec_config_mac_cross",
        "rec_config_text_fuzzy",
    }
    checks = []
    for case in cases:
        if case["case_id"] in critical_ids:
            checks.append({
                "case": case["case_id"],
                "ids": case["actual_ids"],
                "expected_ids": case["expected_ids"],
                "unexpected_ids": case["unexpected_ids"],
                "missing_ids": case["missing_ids"],
                "highlight": case["has_highlight"],
                "line_hits": case["line_hits"],
                "interference_hit_details": case.get("interference_hit_details", []),
                "verdict": case["verdict"],
                "recommendation": case["recommendation"],
            })
    return {
        "opensearch": {
            "url": BASE_URL,
            "version": version["number"],
            "build_hash": version["build_hash"],
            "lucene_version": version["lucene_version"],
        },
        "checks": checks,
    }


def main():
    version = get_json("/")["version"]
    mock = load_mock_docs()
    cases = []
    started = time.time()
    for spec in FIELD_SPECS:
        for input_def in INPUTS:
            for mode in SEARCH_MODES:
                cases.append(run_field_case(mock, spec, input_def, mode))
    for rec in RECOMMENDED_CASES:
        cases.append(run_recommended_case(rec))

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "opensearch": {
            "url": BASE_URL,
            "version": version["number"],
            "build_hash": version["build_hash"],
            "lucene_version": version["lucene_version"],
        },
        "matrix_dimensions": {
            "field_count": len(FIELD_SPECS),
            "input_count": len(INPUTS),
            "search_mode_count": len(SEARCH_MODES),
            "case_count": len(cases),
        },
        "field_specs": FIELD_SPECS,
        "inputs": INPUTS,
        "test_data": build_test_data_rows(mock),
        "field_config": load_mapping_rows(),
        "cases": cases,
        "pivot_summary": aggregate(cases),
        "limitations": limitation_rows(cases),
        "duration_seconds": round(time.time() - started, 3),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    VERIFY_OUTPUT.write_text(json.dumps(verification_report(version, cases), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "verification_report": str(VERIFY_OUTPUT),
        "case_count": len(cases),
        "recommendation_counts": {
            name: sum(1 for case in cases if case["recommendation"] == name)
            for name in ["推荐", "可用但有限制", "不推荐", "不可用", "不适用"]
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"matrix generation failed: {exc}", file=sys.stderr)
        sys.exit(1)
