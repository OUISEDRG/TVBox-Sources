"""Network health and metadata-only upstream audit. No third-party code is executed."""
import argparse
import datetime as dt
import http.client
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

def fetch_json(url):
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
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return "unknown", None
        try:
            return "ok", json.loads(data)
        except (ValueError, UnicodeError):
            return "fail", None
    finally:
        conn.close()

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

def run_health():
    registry, policy, deps = (read(p) for p in ("config/registry.json","config/policy.json","config/dependencies.json"))
    old = read("reports/health.json")
    build(registry, policy, deps, old.get("sites", {}))
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
    build(registry, policy, deps, records)
    old.update(status="checked" if records else "no_eligible_sites", sites=records,
               health_checked_on=date, note="Interface checks only; no device playback tested")
    save("config/registry.json", registry)
    save("reports/health.json", old)
    print("Health checks:", len(records), "eligible sites; no device playback tests")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audit", action="store_true")
    a = p.parse_args()
    audit_only() if a.audit else run_health()
