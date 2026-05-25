#!/usr/bin/env python3
import json
import os
import pathlib
import re
import sys
import urllib.request

BASE_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")
ROOT = pathlib.Path(__file__).resolve().parents[1]


def post(path, body):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def norm_mac(value):
    return re.sub(r"[:.\-]", "", value).lower()


def line_hits(config, query, kind):
    lines = config.splitlines()
    hits = []
    if kind == "ip":
        pattern = re.compile(rf"(?<![0-9A-Fa-f:.]){re.escape(query)}(?![0-9A-Fa-f:.])", re.I)
        for no, line in enumerate(lines, 1):
            if pattern.search(line):
                hits.append({"line": no, "text": line})
    elif kind == "mac":
        q = norm_mac(query)
        for no, line in enumerate(lines, 1):
            if q in norm_mac(line):
                hits.append({"line": no, "text": line})
    else:
        pattern = re.compile(re.escape(query), re.I)
        for no, line in enumerate(lines, 1):
            if pattern.search(line):
                hits.append({"line": no, "text": line})
    return hits


def search_structured_exact_ip(ip):
    return post("/structured-devices-v1/_search", {
        "size": 10,
        "query": {
            "bool": {
                "should": [
                    {"term": {"ip_address": ip}},
                    {"term": {"ip_keyword": ip}},
                    {"match_phrase": {"ip_keyword.text": ip}},
                    {"match_phrase": {"attributes.text": ip}},
                    {"match_phrase": {"description": ip}}
                ],
                "minimum_should_match": 1
            }
        },
        "highlight": {
            "require_field_match": False,
            "fields": {
                "ip_keyword": {"type": "unified", "force_source": True},
                "attributes.text": {"type": "unified", "force_source": True},
                "description": {"type": "unified"}
            }
        }
    })


def search_configs_exact_ip(ip):
    return post("/device-configs-v1/_search", {
        "size": 10,
        "query": {"match_phrase": {"config": ip}},
        "highlight": {
            "fields": {
                "config": {"type": "unified", "number_of_fragments": 5}
            }
        }
    })


def search_structured_exact_mac(mac):
    return post("/structured-devices-v1/_search", {
        "size": 10,
        "query": {
            "bool": {
                "should": [
                    {"match": {"mac": mac}},
                    {"match": {"mac.mac": mac}},
                    {"match": {"attributes.mac": mac}},
                    {"match": {"description.mac": mac}}
                ],
                "minimum_should_match": 1
            }
        },
        "highlight": {
            "require_field_match": False,
            "fields": {
                "mac": {"type": "unified", "force_source": True},
                "attributes.mac": {"type": "unified", "force_source": True},
                "description": {"type": "unified"}
            }
        }
    })


def search_configs_exact_mac(mac):
    return post("/device-configs-v1/_search", {
        "size": 10,
        "query": {"match": {"config.mac": mac}},
        "highlight": {
            "require_field_match": False,
            "fields": {
                "config": {"type": "unified", "number_of_fragments": 5},
                "config.mac": {"type": "unified", "number_of_fragments": 5}
            }
        }
    })


def search_structured_fuzzy_text(text):
    return post("/structured-devices-v1/_search", {
        "size": 10,
        "query": {
            "bool": {
                "should": [
                    {"match": {"name.ngram": text}},
                    {"match": {"description.ngram": text}},
                    {"wildcard": {"attributes.wild": {"value": f"*{text.lower()}*", "case_insensitive": True}}},
                    {"wildcard": {"description.wild": {"value": f"*{text.lower()}*", "case_insensitive": True}}}
                ],
                "minimum_should_match": 1
            }
        },
        "highlight": {
            "require_field_match": False,
            "fields": {
                "name": {"type": "unified"},
                "description": {"type": "unified"},
                "attributes.text": {"type": "unified", "force_source": True}
            }
        }
    })


def search_configs_fuzzy(text):
    return post("/device-configs-v1/_search", {
        "size": 10,
        "query": {
            "bool": {
                "should": [
                    {"match_phrase": {"config": text}},
                    {"match": {"config.ngram": text}},
                    {"wildcard": {"config.wild": {"value": f"*{text.lower()}*", "case_insensitive": True}}}
                ],
                "minimum_should_match": 1
            }
        },
        "highlight": {
            "fields": {
                "config": {"type": "unified", "number_of_fragments": 5}
            }
        }
    })


def ids(result):
    return [hit["_id"] for hit in result["hits"]["hits"]]


def has_highlight(result):
    return any(hit.get("highlight") for hit in result["hits"]["hits"])


def assert_highlight(label, result):
    if not has_highlight(result):
        raise AssertionError(f"{label}: expected at least one highlighted hit")


def assert_line_hits(label, line_hit_map):
    empty = {doc_id: hits for doc_id, hits in line_hit_map.items() if not hits}
    if empty:
        raise AssertionError(f"{label}: expected line hits for every document, empty={sorted(empty)}")


def assert_contains_only(label, result, must_include, must_exclude=()):
    found = set(ids(result))
    missing = set(must_include) - found
    unexpected = set(must_exclude) & found
    if missing or unexpected:
        raise AssertionError(f"{label}: found={sorted(found)} missing={sorted(missing)} unexpected={sorted(unexpected)}")


def main():
    version = get("/")["version"]
    checks = []

    structured_ip = search_structured_exact_ip("10.10.10.1")
    assert_contains_only("structured exact ipv4", structured_ip, ["dev-001"], ["dev-002"])
    assert_highlight("structured exact ipv4", structured_ip)
    checks.append({"case": "structured exact ipv4 10.10.10.1", "ids": ids(structured_ip), "highlight": has_highlight(structured_ip)})

    structured_ipv6 = search_structured_exact_ip("2001:db8::1")
    assert_contains_only("structured exact ipv6", structured_ipv6, ["dev-003"], ["dev-002"])
    assert_highlight("structured exact ipv6", structured_ipv6)
    checks.append({"case": "structured exact ipv6 2001:db8::1", "ids": ids(structured_ipv6), "highlight": has_highlight(structured_ipv6)})

    config_ip = search_configs_exact_ip("10.10.10.1")
    assert_contains_only("config exact ipv4", config_ip, ["cfg-001", "cfg-003"], ["cfg-002"])
    cfg_line_hits = {
        hit["_id"]: line_hits(hit["_source"]["config"], "10.10.10.1", "ip")
        for hit in config_ip["hits"]["hits"]
    }
    assert_highlight("config exact ipv4", config_ip)
    assert_line_hits("config exact ipv4", cfg_line_hits)
    checks.append({"case": "config exact ipv4 with line numbers", "ids": ids(config_ip), "highlight": has_highlight(config_ip), "line_hits": cfg_line_hits})

    config_ipv6 = search_configs_exact_ip("2001:db8::1")
    assert_contains_only("config exact ipv6", config_ipv6, ["cfg-003"], ["cfg-001", "cfg-002"])
    cfg_ipv6_line_hits = {
        hit["_id"]: line_hits(hit["_source"]["config"], "2001:db8::1", "ip")
        for hit in config_ipv6["hits"]["hits"]
    }
    assert_highlight("config exact ipv6", config_ipv6)
    assert_line_hits("config exact ipv6", cfg_ipv6_line_hits)
    checks.append({"case": "config exact ipv6 with line numbers", "ids": ids(config_ipv6), "highlight": has_highlight(config_ipv6), "line_hits": cfg_ipv6_line_hits})

    structured_mac = search_structured_exact_mac("4a:a9:59:4b:b6:2f")
    assert_contains_only("structured exact mac cross-format", structured_mac, ["dev-001", "dev-003"], [])
    assert_highlight("structured exact mac cross-format", structured_mac)
    checks.append({"case": "structured exact mac cross-format", "ids": ids(structured_mac), "highlight": has_highlight(structured_mac)})

    structured_dot_mac = search_structured_exact_mac("00:11:22:33:44:55")
    assert_contains_only("structured exact mac dot-format storage", structured_dot_mac, ["dev-004"], [])
    assert_highlight("structured exact mac dot-format storage", structured_dot_mac)
    checks.append({"case": "structured exact mac dot-format storage", "ids": ids(structured_dot_mac), "highlight": has_highlight(structured_dot_mac)})

    config_mac = search_configs_exact_mac("4a:a9:59:4b:b6:2f")
    assert_contains_only("config exact mac cross-format", config_mac, ["cfg-001", "cfg-003"], [])
    mac_line_hits = {
        hit["_id"]: line_hits(hit["_source"]["config"], "4a:a9:59:4b:b6:2f", "mac")
        for hit in config_mac["hits"]["hits"]
    }
    assert_highlight("config exact mac cross-format", config_mac)
    assert_line_hits("config exact mac cross-format", mac_line_hits)
    checks.append({"case": "config exact mac cross-format with line numbers", "ids": ids(config_mac), "highlight": has_highlight(config_mac), "line_hits": mac_line_hits})

    config_dot_mac = search_configs_exact_mac("00:11:22:33:44:55")
    assert_contains_only("config exact mac dot-format storage", config_dot_mac, ["cfg-004"], [])
    dot_mac_line_hits = {
        hit["_id"]: line_hits(hit["_source"]["config"], "00:11:22:33:44:55", "mac")
        for hit in config_dot_mac["hits"]["hits"]
    }
    assert_highlight("config exact mac dot-format storage", config_dot_mac)
    assert_line_hits("config exact mac dot-format storage", dot_mac_line_hits)
    checks.append({"case": "config exact mac dot-format storage with line numbers", "ids": ids(config_dot_mac), "highlight": has_highlight(config_dot_mac), "line_hits": dot_mac_line_hits})

    fuzzy_structured = search_structured_fuzzy_text("gateway")
    assert_contains_only("structured fuzzy/common text", fuzzy_structured, ["dev-001"], [])
    assert_highlight("structured fuzzy/common text", fuzzy_structured)
    checks.append({"case": "structured fuzzy/common text gateway", "ids": ids(fuzzy_structured), "highlight": has_highlight(fuzzy_structured)})

    fuzzy_config = search_configs_fuzzy("allow-admin")
    assert_contains_only("config fuzzy/common text", fuzzy_config, ["cfg-003"], [])
    allow_line_hits = {
        hit["_id"]: line_hits(hit["_source"]["config"], "allow-admin", "text")
        for hit in fuzzy_config["hits"]["hits"]
    }
    assert_highlight("config fuzzy/common text", fuzzy_config)
    assert_line_hits("config fuzzy/common text", allow_line_hits)
    checks.append({"case": "config fuzzy/common text allow-admin", "ids": ids(fuzzy_config), "highlight": has_highlight(fuzzy_config), "line_hits": allow_line_hits})

    report = {
        "opensearch": {
            "url": BASE_URL,
            "version": version["number"],
            "build_hash": version["build_hash"],
            "lucene_version": version["lucene_version"],
        },
        "checks": checks,
    }
    output = ROOT / "outputs" / "verification-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
