"""P1 configuration builder. Only explicitly reviewed direct HTTPS JSON APIs.
No third-party execution, no network requests, no auto-admission.
User-verified trial entries remain distinct from fully reviewed formal sources.
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
STATES = {"candidate", "pending_playback", "active", "watch", "isolated", "rejected", "trial", "trial_verified"}

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
    require(policy.get("preview_category_limits") == LIMITS, "Preview category policy mismatch")
    require(deps["dependencies"] == [], "Executable dependencies not supported in this release")
    ids, endpoints = set(), set()
    formal = {c: [] for c in LIMITS}
    preview = []
    trial = []
    trial_dependencies = {d["id"]: d for d in deps.get("trial_dependencies", [])}
    for s in registry["sites"]:
        sid = s.get("id", "")
        require(isinstance(sid, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", sid) is not None and sid not in ids, "Invalid or duplicate ID")
        ids.add(sid)
        state = s.get("status")
        require(state in STATES, "Invalid state: " + sid)
        if s.get("reenable_requires_user_retest") is True:
            require(state == "isolated" and s.get("health_managed") is False
                    and s.get("playback_verified") is False,
                    "Manual playback isolation must remain until explicit retest review")
        if state in {"candidate", "isolated", "rejected"}:
            continue
        if state in {"trial", "trial_verified"}:
            require(s.get("approved") is False, "Trial cannot be marked formally approved")
            require(s.get("playback_verified") is (state == "trial_verified"), "Trial playback flag mismatch")
            if state == "trial_verified":
                feedback = s.get("playback_feedback", {})
                require(feedback.get("result") == "ok" and feedback.get("source") == "user_fongmi"
                        and feedback.get("upstream_ref") == s.get("upstream_ref")
                        and isinstance(feedback.get("reported_on"), str)
                        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", feedback["reported_on"]) is not None,
                        "Verified trial requires matching device feedback")
            cats = s.get("categories")
            require(isinstance(cats, list) and bool(cats) and len(set(cats)) == len(cats) and set(cats) <= set(LIMITS), "Invalid trial categories")
            entry = s.get("trial_entry", {})
            require(entry.get("key") == sid and entry.get("name") == s.get("name") and entry.get("api") == s.get("api") and entry.get("type") == s.get("type"), "Trial identity mismatch")
            require(set(entry) <= {"key","name","type","api","searchable","quickSearch","filterable","changeable","playerType","genre","categories","ext"}, "Unexpected trial fields")
            if "ext" in entry:
                require(entry["type"] == 3 and s.get("dependency_id") == "qist-spider"
                        and isinstance(entry["ext"], str)
                        and re.fullmatch(r"https://[A-Za-z0-9.-]+/?", entry["ext"]) is not None
                        and https_url(entry["ext"]), "Invalid trial ext: HTTPS origin only")
            if entry["type"] == 1:
                require(https_url(entry["api"]) and s.get("dependency_id") is None, "Invalid trial direct API")
            elif entry["type"] == 3:
                dep = trial_dependencies.get(s.get("dependency_id"), {})
                ref = s.get("upstream_ref", "")
                require(re.fullmatch(r"[0-9a-f]{40}", ref) is not None and s.get("upstream") == "qist/tvbox", "Invalid trial pin")
                prefix = "https://raw.githubusercontent.com/qist/tvbox/" + ref + "/"
                if s.get("dependency_id") == "qist-spider":
                    require(re.fullmatch(r"csp_[A-Za-z0-9_]+", entry["api"]) is not None and dep.get("url", "").startswith(prefix + "jar/spider.jar;md5;"), "Invalid trial JAR")
                elif s.get("dependency_id") == "qist-python":
                    require(entry["api"] == dep.get("url") and entry["api"].startswith(prefix + "py/") and entry["api"].endswith(".py"), "Invalid trial Python")
                else:
                    raise ValueError("Unknown trial dependency")
            else:
                raise ValueError("Unsupported trial site type")
            normalized = entry["api"].rstrip("/").lower()
            require(normalized not in endpoints, "Duplicate trial endpoint")
            endpoints.add(normalized)
            trial.append((s, entry))
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
        require(sum(category in s["categories"] for s, _ in preview + trial) <= policy["preview_category_limits"][category],
                "Preview category limit exceeded: " + category)
    result["tvbox.json"] = config(list(all_entries.values()))
    # Verified trials precede new, untested candidates; preserve relative order for equal states.
    trial.sort(key=lambda item: item[0]["status"] != "trial_verified")
    result["preview.json"] = config([e for _, e in trial + preview])
    if any(s.get("dependency_id") == "qist-spider" for s, _ in trial):
        result["preview.json"]["spider"] = trial_dependencies["qist-spider"]["url"]
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
