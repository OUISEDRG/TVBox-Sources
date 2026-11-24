"""P1 configuration builder. Only explicitly reviewed direct HTTPS JSON APIs.
No third-party execution, no network requests, no auto-admission.
"""
import argparse
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {"series": 8, "anime": 5, "movies": 8, "short": 5}
BASE = "https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/"
STATES = {"candidate", "pending_playback", "active", "watch", "isolated", "rejected"}

def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))

def require(condition, message):
    if not condition:
        raise ValueError(message)

def https_url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and bool(u.hostname) and
                not u.username and not u.password and not u.query and
                not u.fragment and u.port in (None, 443))
    except ValueError:
        return False

def build(registry, policy, deps, health=None):
    health = health or {}
    require(policy["categories"] == LIMITS and policy["base_url"] == BASE
            and policy["approval_required"] is True, "Fixed policy mismatch")
    require(deps["dependencies"] == [], "Executable dependencies not supported in this release")
    ids, endpoints = set(), set()
    formal = {c: [] for c in LIMITS}
    preview = []
    for s in registry["sites"]:
        sid = s.get("id", "")
        require(isinstance(sid, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", sid) is not None and sid not in ids, "Invalid or duplicate ID")
        ids.add(sid)
        state = s.get("status")
        require(state in STATES, "Invalid state: " + sid)
        if state in {"candidate", "isolated", "rejected"}:
            continue
        name, api = s.get("name"), s.get("api")
        cats, primary = s.get("categories"), s.get("primary_for", [])
        require(isinstance(name, str) and 0 < len(name.strip()) <= 40 and name == name.strip(), "Invalid site name")
        require(isinstance(cats, list) and bool(cats) and len(set(cats)) == len(cats)
                and set(cats) <= set(LIMITS), "Invalid categories")
        require(isinstance(primary, list) and set(primary) <= set(cats), "Invalid primary assignment")
        require(s.get("type") == 1 and s.get("dependency_id") is None and https_url(api), "Only reviewed direct HTTPS JSON APIs supported")
        require(s.get("authorization_reviewed") is True and isinstance(s.get("authorization"), str)
                and bool(s["authorization"].strip()) and s.get("security_reviewed") is True
                and s.get("compatibility_reviewed") is True, "Missing review evidence")
        require(isinstance(s.get("upstream"), str) and bool(s["upstream"].strip()), "Missing upstream")
        normalized = api.rstrip("/").lower()
        require(normalized not in endpoints, "Duplicate API endpoint")
        endpoints.add(normalized)
        # Explicit allowlist of emitted fields; never pass through arbitrary upstream objects.
        entry = {"key": sid, "name": name, "type": 1, "api": api}
        if state == "pending_playback":
            preview.append((s, entry))
            continue
        require(s.get("approved") is True and s.get("playback_verified") is True, "Formal site requires approval and device playback verification")
        score = s.get("score")
        require(type(score) in (int, float) and 80 <= score <= 100, "Formal site score must be 80-100")
        for category in cats:
            formal[category].append((s, entry))
    def config(entries):
        return {"sites": entries, "parses": [], "lives": [], "wallpaper": BASE + "assets/wallpaper.png"}
    result = {}
    all_entries = {}
    for category, items in formal.items():
        require(len(items) <= LIMITS[category], "Category limit exceeded: " + category)
        require(sum(category in s.get("primary_for", []) for s, _ in items) <= 1, "Multiple active primaries")
        items.sort(key=lambda item: (item[0]["status"] != "active",
                                     category not in item[0].get("primary_for", []),
                                     -(health.get(item[0]["id"], {}).get("success_rate") or 0) if health.get(item[0]["id"], {}).get("sample_count", 0) >= 3 else -item[0]["score"] / 100,
                                     -item[0]["score"], item[0]["id"]))
        entries = [entry for _, entry in items]
        result["sources/" + category + ".json"] = config(entries)
        for entry in entries:
            all_entries.setdefault(entry["key"], entry)
    for category in LIMITS:
        require(sum(category in s["categories"] for s, _ in preview) <= policy["initial_candidates_per_category"],
                "Initial preview category limit exceeded")
    result["tvbox.json"] = config(list(all_entries.values()))
    result["preview.json"] = config([e for _, e in sorted(preview, key=lambda item: item[0]["id"])])
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit-upstreams", action="store_true")
    args = parser.parse_args()
    if args.audit_upstreams:
        from health import audit_only
        audit_only()
        return
    result = build(read("config/registry.json"), read("config/policy.json"), read("config/dependencies.json"), read("reports/health.json").get("sites", {}))
    if args.check:
        require(all(read(path) == data for path, data in result.items()), "Generated files drift")
        print("Configuration check passed")
        return
    # All entries validated before any write. Git commits must include the entire generated set.
    with tempfile.TemporaryDirectory(dir=ROOT) as stage:
        for path, data in result.items():
            target = Path(stage) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for path in result:
            (Path(stage) / path).replace(ROOT / path)
    print("Configuration generated; playback is not tested by this script")

if __name__ == "__main__":
    main()
