"""Network health and metadata-only upstream audit. No third-party code is executed."""
import argparse
import copy
import datetime as dt
import http.client
import hashlib
import re
import ipaddress
import json
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from sync import read, build, ROOT, https_url

UTC8 = dt.timezone(dt.timedelta(hours=8))
MAX_BYTES = 2 * 1024 * 1024
RAW_HOST = "raw.githubusercontent.com"

def day():
    return dt.datetime.now(UTC8).date().isoformat()

def fetch_bytes(url, limit=MAX_BYTES):
    """HTTPS only, no redirects, no credentials, public IPs only; connect to vetted IP."""
    u = urlsplit(url)
    if not https_url(url.split("?", 1)[0]) or u.fragment:
        raise ValueError("unsafe URL")
    addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
    ips = sorted({a[4][0] for a in addresses})
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("nonpublic address")
    conn = http.client.HTTPSConnection(u.hostname, 443, timeout=12, context=ssl.create_default_context())
    def connect_pinned(address, timeout=None, source_address=None):
        return socket.create_connection((ips[0], 443), timeout, source_address)
    conn._create_connection = connect_pinned
    try:
        conn.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""),
                     headers={"Accept": "application/json,text/plain", "User-Agent": "TVBox-Sources-health/1.0", "Accept-Encoding": "identity"})
        r = conn.getresponse()
        if r.status in (401, 403, 429) or 300 <= r.status < 400:
            return "unknown", None
        if r.status != 200:
            return ("fail" if r.status in (404, 410, 500, 502, 503, 504) else "unknown"), None
        data = r.read(limit + 1)
        if len(data) > limit:
            return "unknown", None
        return "ok", data
    finally:
        conn.close()

def fetch_json(url):
    state, data = fetch_bytes(url)
    if state != "ok":
        return state, None
    try:
        return "ok", json.loads(data)
    except (ValueError, UnicodeError):
        return "fail", None

def safe_fetch(url, getter=fetch_json):
    try:
        return getter(url)
    except (OSError, ValueError, http.client.HTTPException):
        return "unknown", None

def probe(site, getter=fetch_json):
    """List, category, details and optional authorized search; never fetch video."""
    api = site["api"]
    def call(params):
        result, obj = safe_fetch(api + ("?" + urlencode(params) if params else ""), getter)
        if result != "ok":
            return result, {}
        if not isinstance(obj, dict):
            return "fail", {}
        return "ok", obj
    result, root = call({})
    if result != "ok":
        return result
    classes = root.get("class")
    if not isinstance(classes, list) or not classes:
        return "fail"
    result, listing = call({"ac": "videolist", "pg": 1})
    if result != "ok":
        return result
    items = listing.get("list")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return "fail"
    vid = items[0].get("vod_id")
    if not isinstance(vid, (str, int)) or not str(vid):
        return "fail"
    result, details = call({"ac": "detail", "ids": str(vid)})
    if result != "ok":
        return result
    if not isinstance(details.get("list"), list) or not details["list"]:
        return "fail"
    if site.get("authorized_search_term"):
        result, search = call({"ac": "videolist", "wd": site["authorized_search_term"]})
        if result != "ok":
            return result
        if not isinstance(search.get("list"), list) or not search["list"]:
            return "fail"
    return "ok"

def transition(site, prior, outcome, date):
    """At most one result per calendar day. Unknown results never count as failure."""
    rec = dict(prior or {})
    hist = dict(rec.get("history", {}))
    cutoff = (dt.date.fromisoformat(date) - dt.timedelta(days=6)).isoformat()
    hist = {d: v for d, v in hist.items() if cutoff <= d <= date}
    hist[date] = outcome
    known = [v for _, v in sorted(hist.items()) if v in ("ok", "fail")]
    consecutive_failures = 0
    consecutive_ok = 0
    for i in range(7):
        d = (dt.date.fromisoformat(date) - dt.timedelta(days=i)).isoformat()
        if hist.get(d) != "fail":
            break
        consecutive_failures += 1
    for i in range(7):
        d = (dt.date.fromisoformat(date) - dt.timedelta(days=i)).isoformat()
        if hist.get(d) != "ok":
            break
        consecutive_ok += 1
    rec.update(history=hist, last_result=outcome, last_date=date,
               sample_count=len(known), success_rate=(known.count("ok") / len(known) if known else None),
               failure_days=consecutive_failures, recovery_days=consecutive_ok,
               playback_test="not_performed")
    if site["status"] in ("active", "watch") and consecutive_failures >= 3:
        site["status"] = "isolated"
        site["health_managed"] = True
    elif site["status"] == "active" and consecutive_failures >= 2:
        site["status"] = "watch"
        site["health_managed"] = True
    elif site["status"] in ("watch", "isolated") and site.get("health_managed") is True and consecutive_ok >= 2:
        if all(site.get(k) is True for k in ("approved", "playback_verified", "authorization_reviewed", "security_reviewed", "compatibility_reviewed")):
            site["status"] = "active"
            site["health_managed"] = False
    return rec

def audit_upstreams(config, previous=None, getter=fetch_json):
    """Read public config metadata only; no links, credentials, site payloads or scripts are copied."""
    results = {}
    for u in config["upstreams"]:
        uid = u["id"]
        url = u["audit_url"]
        if urlsplit(url).hostname != RAW_HOST or not https_url(url):
            raise ValueError("Unapproved audit host")
        state, data = safe_fetch(url, getter)
        if state == "ok" and isinstance(data, dict) and isinstance(data.get("sites"), list):
            counts = {}
            for site in data["sites"]:
                if isinstance(site, dict):
                    kind = str(site.get("type"))[:10]
                    if kind not in ("0", "1", "2", "3", "4"):
                        kind = "other"
                    counts[kind] = counts.get(kind, 0) + 1
            results[uid] = {"status":"readable", "site_count":len(data["sites"]), "types":counts,
                            "global_spider": bool(data.get("spider")), "admission":"blocked_pending_rights_and_security_review"}
        else:
            results[uid] = {"status": state if state != "ok" else "invalid_config",
                            "admission":"blocked", "last_readable": (previous or {}).get(uid, {}).get("site_count")}
    return results

def save(path, obj):
    target = ROOT / path
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)

def audit_only():
    report = read("reports/health.json")
    report["upstream_audit"] = audit_upstreams(read("config/upstreams.json"), report.get("upstream_audit"))
    report["upstream_audited_on"] = day()
    save("reports/health.json", report)
    print("Upstream metadata audit completed; no sites imported")

def mass_loss(before, after):
    old = {s['id'] for s in before['sites'] if s['status'] in ('active', 'watch')}
    new = {s['id'] for s in after['sites'] if s['status'] in ('active', 'watch')}
    return bool(old) and len(old - new) * 2 >= len(old)

def run_health():
    registry, policy, deps = (read(p) for p in ("config/registry.json","config/policy.json","config/dependencies.json"))
    old = read("reports/health.json")
    build(registry, policy, deps, old.get("sites", {}))
    before = copy.deepcopy(registry)
    records = {}
    date = day()
    for s in registry["sites"]:
        if s["status"] not in ("active", "watch", "pending_playback") and not (s["status"] == "isolated" and s.get("health_managed") is True):
            continue
        if s.get("type") != 1 or not https_url(s.get("api")) or not all(s.get(k) is True for k in ("authorization_reviewed","security_reviewed","compatibility_reviewed")):
            continue
        result = probe(s)
        if result == "fail":
            result = probe(s) # recheck a definitive failure
        records[s["id"]] = transition(s, old.get("sites", {}).get(s["id"]), result, date)
    blocked = mass_loss(before, registry)
    if blocked:
        registry = before
    build(registry, policy, deps, records)
    old.update(status="bulk_loss_hold" if blocked else ("checked" if records else "no_eligible_sites"), sites=records,
               health_checked_on=date, note="Interface checks only; no device playback tested")
    save("config/registry.json", registry)
    save("reports/health.json", old)
    print("Health checks:", len(records), "eligible sites; no device playback tests")
    if blocked:
        print("Bulk loss held: human review required; formal registry unchanged")

def frozen_guard(registry, policy):
    """Only previously selected IDs may be visible; maintenance cannot add sites."""
    cfg = policy["maintenance"]
    if cfg["mode"] != "frozen_roster" or any(cfg[k] is not False for k in
            ("automatic_admission","automatic_dependency_updates","automatic_trial_removal")):
        raise ValueError("Frozen maintenance policy changed")
    roster = cfg["roster"]
    if len(roster) != len(set(roster)):
        raise ValueError("Duplicate frozen roster ID")
    actual = {s["id"] for s in registry["sites"] if s["status"] in ("trial","trial_verified","pending_playback","active","watch")}
    if not actual <= set(roster):
        raise ValueError("Unexpected new visible site in frozen roster")

def check_dependencies(deps, getter=fetch_bytes):
    """Read pinned bytes, never import, unpack or execute. Persist only checksums."""
    results = {}
    for dep in deps.get("trial_dependencies", []):
        url = dep["url"].split(";md5;", 1)[0]
        if not https_url(url) or not re.fullmatch(r"https://raw\.githubusercontent\.com/qist/tvbox/[a-f0-9]{40}/(?:jar/spider\.jar|py/[A-Za-z0-9%_.-]+\.py)", url):
            raise ValueError("Unexpected dependency URL")
        try:
            state, data = getter(url)
        except (OSError, ValueError, http.client.HTTPException):
            state, data = "unknown", None
        if state != "ok":
            results[dep["id"]] = {"status":state, "executed":False}
            continue
        blob = hashlib.sha1(("blob " + str(len(data)) + "\0").encode() + data).hexdigest()
        sha = hashlib.sha256(data).hexdigest()
        match = blob == dep.get("git_blob") and len(data) == dep.get("size")
        if dep.get("upstream_md5"):
            match = match and hashlib.md5(data, usedforsecurity=False).hexdigest() == dep["upstream_md5"]
        if dep.get("sha256"):
            match = match and sha == dep["sha256"]
        results[dep["id"]] = {"status":"integrity_ok" if match else "integrity_mismatch",
                             "sha256":sha,"git_blob_match":blob == dep.get("git_blob"),"bytes":len(data),
                             "executed":False,"security_review":"unverified"}
    return results

def compare_upstream_dependencies(deps, getter=fetch_bytes):
    """Inspect latest bytes at corresponding upstream paths, without changing pins."""
    result = {}
    for dep in deps.get("trial_dependencies", []):
        pinned = dep["url"].split(";md5;", 1)[0]
        if not re.fullmatch(r"https://raw\.githubusercontent\.com/qist/tvbox/[a-f0-9]{40}/(?:jar/spider\.jar|py/[A-Za-z0-9%_.-]+\.py)", pinned):
            raise ValueError("Unexpected dependency path")
        url = re.sub(r"(?<=/qist/tvbox/)[a-f0-9]{40}/", "master/", pinned, count=1)
        try:
            state, data = getter(url)
        except (OSError, ValueError, http.client.HTTPException):
            state, data = "unknown", None
        if state != "ok":
            result[dep["id"]] = {"status":state,"executed":False}
            continue
        digest = hashlib.sha256(data).hexdigest()
        result[dep["id"]] = {"status":"unchanged" if digest == dep.get("sha256") else "changed_upstream",
                             "sha256":digest,"executed":False}
    return result

def compare_selected(registry, config, getter=fetch_json):
    """Compare retained sites to latest qist metadata; never import changed definitions."""
    url = next(u["audit_url"] for u in config["upstreams"] if u["id"] == "qist")
    if url != "https://raw.githubusercontent.com/qist/tvbox/master/jsm.json":
        raise ValueError("Unexpected selected upstream")
    state, data = safe_fetch(url, getter)
    sites = [s for s in registry["sites"] if s["status"] == "trial_verified"]
    if state != "ok" or not isinstance(data, dict) or not isinstance(data.get("sites"), list):
        return {s["id"]:{"status":"unknown"} for s in sites}
    by_key = {}
    for item in data["sites"]:
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            by_key.setdefault(item["key"], []).append(item)
    result = {}
    for s in sites:
        matches = by_key.get(s["upstream_key"], [])
        if not matches:
            result[s["id"]] = {"status":"missing_upstream"}
            continue
        if len(matches) != 1:
            result[s["id"]] = {"status":"duplicate_upstream_key"}
            continue
        remote = matches[0]
        entry = s["trial_entry"]
        api = remote.get("api")
        if isinstance(api,str) and api.startswith("./"):
            from urllib.parse import quote
            api = "https://raw.githubusercontent.com/qist/tvbox/" + s["upstream_ref"] + "/" + quote(api[2:], safe="/")
        fields = [k for k in ("type","ext","searchable","quickSearch","filterable","changeable","playerType","genre")
                  if remote.get(k) != entry.get(k)]
        if api != entry["api"]:
            fields.append("api")
        # Category lists may be intentionally curated locally; not a configuration change.
        result[s["id"]] = {"status":"changed_upstream" if fields else "unchanged",
                           "changed_fields":fields}
    return result

def maintenance_snapshot(registry, policy, deps, upstreams, old, mode="full",
                         dep_getter=fetch_bytes, json_getter=fetch_json):
    """Frozen mode: observe only; never mutate registry, dependencies or subscriptions."""
    frozen_guard(registry, policy)
    snapshot = copy.deepcopy(old)
    date = day()
    if mode in ("sync","full"):
        snapshot["upstream_audit"] = audit_upstreams(upstreams, snapshot.get("upstream_audit"), json_getter)
        snapshot["upstream_audited_on"] = date
        snapshot["retained_upstream"] = compare_selected(registry, upstreams, json_getter)
        snapshot["upstream_dependency_changes"] = compare_upstream_dependencies(deps, dep_getter)
    if mode in ("health","full"):
        snapshot["dependency_integrity"] = check_dependencies(deps, dep_getter)
        records = {}
        for s in registry["sites"]:
            if s["status"] != "trial_verified":
                continue
            # Network checks only for direct APIs; no playback, no scraping code.
            if s["type"] == 1 and https_url(s["api"]):
                result = probe(s, json_getter)
                if result == "fail":
                    result = probe(s, json_getter)
                rec = transition(copy.deepcopy(s), snapshot.get("trial_health",{}).get(s["id"]), result, date)
                rec["status"] = ("retest_required" if rec["failure_days"] >= 3 else
                                 "watch" if rec["failure_days"] >= 2 else result)
            else:
                dep = snapshot["dependency_integrity"].get(s.get("dependency_id"),{})
                rec = {"status":"dependency_only", "dependency_status":dep.get("status","unknown"),
                       "playback_test":"not_performed","last_date":date}
            records[s["id"]] = rec
        snapshot["trial_health"] = records
        snapshot["health_checked_on"] = date
    issues = []
    for field in ("dependency_integrity","upstream_dependency_changes","retained_upstream","trial_health"):
        for sid, rec in snapshot.get(field,{}).items():
            status = rec.get("status")
            if status not in ("integrity_ok","unchanged","ok","dependency_only") or rec.get("dependency_status","integrity_ok") != "integrity_ok":
                issues.append({"scope":field,"id":sid,"status":status})
    snapshot["status"] = "frozen_roster_monitored"
    snapshot["note"] = "Metadata and integrity checks only; device playback feedback is separate."
    snapshot["maintenance"] = {"mode":"frozen_roster","status":"review_required" if issues else "checked",
                               "issues":issues,"retained":sum(s["status"]=="trial_verified" for s in registry["sites"]),
                               "last_run_on":date,"playback_test":"not_performed"}
    return snapshot

def frozen_run(mode, dry_run=False):
    registry, policy, deps, upstreams, old = (read(p) for p in
        ("config/registry.json","config/policy.json","config/dependencies.json","config/upstreams.json","reports/health.json"))
    build(registry, policy, deps, old.get("sites",{}))
    result = maintenance_snapshot(registry, policy, deps, upstreams, old, mode)
    # Print limited report for real CI network verification, not third-party payloads.
    for field in ("dependency_integrity","upstream_dependency_changes","retained_upstream","trial_health","maintenance"):
        print(field + ": " + json.dumps(result.get(field,{}), ensure_ascii=False, sort_keys=True))
    if not dry_run:
        save("reports/health.json", result)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audit", action="store_true")
    p.add_argument("--mode", choices=("sync","health","full"), default="health")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    frozen_run("sync" if a.audit else a.mode, a.dry_run)
