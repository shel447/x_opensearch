#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")
ROOT = pathlib.Path(__file__).resolve().parents[1]

INDICES = {
    "structured-devices-v1": ROOT / "opensearch" / "indices" / "structured-devices-v1.json",
    "device-configs-v1": ROOT / "opensearch" / "indices" / "device-configs-v1.json",
}

STRUCTURED_DOCS = [
    {
        "_id": "dev-001",
        "device_id": "dev-001",
        "device_type": "switch",
        "name": "sw-core-01",
        "ip_address": "10.10.10.1",
        "ip_keyword": "10.10.10.1",
        "mac": "4a-a9-59-4b-b6-2f",
        "vendor": "Acme",
        "status": "active",
        "port_count": 48,
        "last_seen": "2026-05-22T08:15:00Z",
        "attributes": "mgmt=10.10.10.1 uplink-mac=4aa9.594b.b62f site=shanghai zone=A",
        "description": "Core switch. Gateway 10.10.10.1 uses MAC 4a-a9-59-4b-b6-2f on VLAN10.",
    },
    {
        "_id": "dev-002",
        "device_id": "dev-002",
        "device_type": "router",
        "name": "rt-edge-01",
        "ip_address": "10.10.10.11",
        "ip_keyword": "10.10.10.11",
        "mac": "aa:bb:cc:dd:ee:ff",
        "vendor": "Acme",
        "status": "active",
        "port_count": 8,
        "last_seen": "2026-05-22T08:17:00Z",
        "attributes": "wan=10.10.10.11 peer=2001:db8::2 mac=aa-bb-cc-dd-ee-ff",
        "description": "Edge router with address 10.10.10.11. It must not match exact 10.10.10.1.",
    },
    {
        "_id": "dev-003",
        "device_id": "dev-003",
        "device_type": "firewall",
        "name": "fw-v6-01",
        "ip_address": "2001:db8::1",
        "ip_keyword": "2001:db8::1",
        "mac": "4aa9594bb62f",
        "vendor": "Zenith",
        "status": "standby",
        "port_count": 16,
        "last_seen": "2026-05-22T08:19:00Z",
        "attributes": "ipv6=2001:db8::1 mirror-mac=4a:a9:59:4b:b6:2f",
        "description": "IPv6 firewall with compact MAC 4aa9594bb62f.",
    },
    {
        "_id": "dev-004",
        "device_id": "dev-004",
        "device_type": "switch",
        "name": "sw-access-legacy",
        "ip_keyword": "010.010.010.001",
        "mac": "0011.2233.4455",
        "vendor": "Legacy",
        "status": "quarantine",
        "port_count": 24,
        "last_seen": "2026-05-22T08:21:00Z",
        "attributes": "legacy-ip=010.010.010.001 legacy-mac=00-11-22-33-44-55",
        "description": "Legacy export keeps leading-zero IPv4 text 010.010.010.001; ip type cannot index it as a valid IPv4 literal.",
    },
    {
        "_id": "dev-005",
        "device_id": "dev-005",
        "device_type": "ap",
        "name": "ap-lobby-01",
        "ip_address": "172.16.5.25",
        "ip_keyword": "172.16.5.25",
        "mac": "de-ad-be-ef-00-01",
        "vendor": "Wave",
        "status": "active",
        "port_count": 2,
        "last_seen": "2026-05-22T08:23:00Z",
        "attributes": "ssid=guest changed=2026-05-22T08:23:00 mac=dead.beef.0001",
        "description": "Lobby AP, guest wireless access, DHCP relay 172.16.5.1.",
    },
    {
        "_id": "dev-006",
        "device_id": "dev-006",
        "device_type": "switch",
        "name": "sw-noise-time-59",
        "ip_address": "10.10.10.100",
        "ip_keyword": "10.10.10.100",
        "mac": "12:34:56:78:90:ab",
        "vendor": "NoiseLab",
        "status": "active",
        "port_count": 59,
        "last_seen": "2026-05-23T12:59:06Z",
        "attributes": "event_time=2026-05-23 12:59:06 interface=Ethernet1/0/59 vlan=59 firmware=4.9.59 build=06 serial=4aa9594bb62f trace=4aa959",
        "description": "Noise sample: not a target MAC. Time 2026-05-23 12:59:06, VLAN 59, port 06, model X59-B6, administrator note.",
    },
    {
        "_id": "dev-007",
        "device_id": "dev-007",
        "device_type": "router",
        "name": "rt-noise-ip-boundary",
        "ip_address": "110.10.10.1",
        "ip_keyword": "110.10.10.1",
        "mac": "66:77:88:99:aa:bb",
        "vendor": "NoiseLab",
        "status": "active",
        "port_count": 6,
        "last_seen": "2026-05-23T13:06:59Z",
        "attributes": "neighbor=10.10.10.100 alt=110.10.10.1 ipv6=2001:db8::1:59 label=admin-down",
        "description": "Boundary sample: 110.10.10.1 and 10.10.10.100 should not satisfy exact 10.10.10.1 intent.",
    },
]

CONFIG_DOCS = [
    {
        "_id": "cfg-001",
        "config_id": "cfg-001",
        "device_id": "dev-001",
        "collected_at": "2026-05-22T08:15:00Z",
        "config": "\n".join(
            [
                "hostname sw-core-01",
                "interface Vlan10",
                " ip address 10.10.10.1 255.255.255.0",
                " mac-address 4a-a9-59-4b-b6-2f",
                " description User gateway VLAN",
                " logging host 192.168.100.10",
                " ntp server 2001:db8::10",
            ]
        ),
    },
    {
        "_id": "cfg-002",
        "config_id": "cfg-002",
        "device_id": "dev-002",
        "collected_at": "2026-05-22T08:17:00Z",
        "config": "\n".join(
            [
                "hostname rt-edge-01",
                "interface GigabitEthernet0/0",
                " ip address 10.10.10.11 255.255.255.0",
                " standby mac-address aa:bb:cc:dd:ee:ff",
                " route-map INTERNET permit 10",
                " set ipv6 next-hop 2001:db8::2",
            ]
        ),
    },
    {
        "_id": "cfg-003",
        "config_id": "cfg-003",
        "device_id": "dev-003",
        "collected_at": "2026-05-22T08:19:00Z",
        "config": "\n".join(
            [
                "hostname fw-v6-01",
                "set interface ethernet1/1 ipv6 2001:db8::1/64",
                "set interface ethernet1/1 mac 4aa9.594b.b62f",
                "set rulebase security rules allow-admin source 10.10.10.1",
                "set rulebase security rules allow-admin log-start yes",
            ]
        ),
    },
    {
        "_id": "cfg-004",
        "config_id": "cfg-004",
        "device_id": "dev-004",
        "collected_at": "2026-05-22T08:21:00Z",
        "config": "\n".join(
            [
                "hostname sw-access-legacy",
                "interface vlan 1",
                " ip address 010.010.010.001 255.255.255.0",
                " mac-address 0011.2233.4455",
                " banner motd legacy device, verify before migration",
            ]
        ),
    },
    {
        "_id": "cfg-005",
        "config_id": "cfg-005",
        "device_id": "dev-006",
        "collected_at": "2026-05-23T12:59:06Z",
        "config": "\n".join(
            [
                "hostname sw-noise-time-59",
                "clock set 2026-05-23 12:59:06",
                "interface Ethernet1/0/59",
                " switchport access vlan 59",
                " firmware version 4.9.59 build 06",
                " serial-number 4aa9594bb62f",
                " trace-id 4aa959",
                " description administrator touched port 06, not a mac address",
            ]
        ),
    },
    {
        "_id": "cfg-006",
        "config_id": "cfg-006",
        "device_id": "dev-007",
        "collected_at": "2026-05-23T13:06:59Z",
        "config": "\n".join(
            [
                "hostname rt-noise-ip-boundary",
                "interface Loopback10",
                " ip address 110.10.10.1 255.255.255.255",
                " ip route 10.10.10.100 255.255.255.255 Null0",
                " ipv6 address 2001:db8::1:59/128",
                " policy admin-down reason administrator-request",
                " event timestamp 2026-05-23 13:06:59",
            ]
        ),
    },
]


def request(method, path, body=None, expected=(200, 201)):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            if resp.status not in expected:
                raise RuntimeError(f"{method} {path} returned {resp.status}: {payload}")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        if exc.code not in expected:
            raise RuntimeError(f"{method} {path} returned {exc.code}: {payload}") from exc
        return json.loads(payload) if payload else {}


def wait_for_cluster():
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            health = request("GET", "/_cluster/health", expected=(200,))
            if health.get("status") in {"green", "yellow"}:
                return health
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"OpenSearch at {BASE_URL} did not become ready")


def recreate_indices():
    for index in INDICES:
        request("DELETE", f"/{index}", expected=(200, 404))
    for index, file_path in INDICES.items():
        body = json.loads(file_path.read_text(encoding="utf-8"))
        request("PUT", f"/{index}", body, expected=(200,))


def bulk_index(index, docs):
    lines = []
    for doc in docs:
        doc = dict(doc)
        doc_id = doc.pop("_id")
        lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    data = ("\n".join(lines) + "\n").encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/_bulk?refresh=true",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-ndjson"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("errors"):
        failures = [item for item in result["items"] if item["index"].get("error")]
        raise RuntimeError(json.dumps(failures[:5], indent=2, ensure_ascii=False))


def write_mock_snapshot():
    output = {
        "structured-devices-v1": STRUCTURED_DOCS,
        "device-configs-v1": CONFIG_DOCS,
    }
    path = ROOT / "data" / "mock-documents.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    health = wait_for_cluster()
    recreate_indices()
    bulk_index("structured-devices-v1", STRUCTURED_DOCS)
    bulk_index("device-configs-v1", CONFIG_DOCS)
    snapshot = write_mock_snapshot()
    print(json.dumps({
        "opensearch_url": BASE_URL,
        "cluster_status": health.get("status"),
        "indices": list(INDICES),
        "structured_docs": len(STRUCTURED_DOCS),
        "config_docs": len(CONFIG_DOCS),
        "mock_snapshot": str(snapshot),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
