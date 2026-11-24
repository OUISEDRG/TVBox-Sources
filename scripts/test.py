import unittest
from sync import build, read, ROOT, BASE, LIMITS
from health import transition, probe, audit_upstreams, mass_loss

def site(id="one", **kwargs):
    return dict(id=id, name=id, status="active", type=1, api="https://example.com/" + id,
                categories=["series"], primary_for=[], dependency_id=None, upstream="test fixture",
                authorization="synthetic test evidence", authorization_reviewed=True,
                security_reviewed=True, compatibility_reviewed=True, approved=True,
                playback_verified=True, score=90, **{}) | kwargs

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.policy = read("config/policy.json")
        self.deps = {"dependencies": []}
    def build(self, *sites):
        return build({"sites": list(sites)}, self.policy, self.deps)
    def test_limits(self):
        self.assertEqual(sum(LIMITS.values()), 26)
    def test_committed_outputs(self):
        for path, data in build(read("config/registry.json"), self.policy, read("config/dependencies.json"), read("reports/health.json").get("sites", {})).items():
            self.assertEqual(read(path), data, path)
    def test_empty(self):
        result = self.build()
        self.assertEqual(len(result), 6)
        self.assertTrue(all(not x["sites"] for x in result.values()))
    def test_preview_isolation(self):
        r = self.build(site(status="pending_playback", approved=False, playback_verified=False))
        self.assertEqual(len(r["preview.json"]["sites"]), 1)
        self.assertFalse(r["tvbox.json"]["sites"])
    def test_review_required(self):
        for field in ["authorization_reviewed", "security_reviewed", "compatibility_reviewed", "approved", "playback_verified"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(site(**{field: False}))
    def test_reject_duplicate(self):
        with self.assertRaises(ValueError):
            self.build(site(), site())
        with self.assertRaises(ValueError):
            self.build(site(), site("two", api="https://example.com/one"))
    def test_primary(self):
        r = self.build(site("one", score=80, primary_for=["series"]), site("two", score=99))
        self.assertEqual([x["key"] for x in r["sources/series.json"]["sites"]], ["one", "two"])
    def test_multiple_primaries(self):
        with self.assertRaises(ValueError):
            self.build(site("one", primary_for=["series"]), site("two", primary_for=["series"]))
    def test_capacity(self):
        with self.assertRaises(ValueError):
            self.build(*(site(str(i)) for i in range(9)))
    def test_isolated(self):
        self.assertFalse(self.build(site(status="isolated"))["tvbox.json"]["sites"])
    def test_multicategory(self):
        r = self.build(site(categories=["series", "movies"]))
        self.assertEqual(len(r["tvbox.json"]["sites"]), 1)
        self.assertEqual(len(r["sources/movies.json"]["sites"]), 1)
    def test_reject_unsafe(self):
        for changes in [{"api": "http://example.com"}, {"api": "https://user:pass@example.com"}, {"api": "https://example.com/?token=x"}, {"type": 3}, {"dependency_id": "jar"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(site(**changes))
    def test_dependency_gate(self):
        with self.assertRaises(ValueError):
            build({"sites": []}, self.policy, {"dependencies": [{}]})
    def test_policy_change(self):
        with self.assertRaises(ValueError):
            build({"sites": []}, {**self.policy,"categories":{"short":99}}, self.deps)
    def test_trial_preview_only(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        r = build(registry, self.policy, deps)
        trials = [s for s in registry["sites"] if s["status"] in {"trial", "trial_verified"}]
        self.assertTrue(set(s["id"] for s in trials) <= {e["key"] for e in r["preview.json"]["sites"]})
        self.assertFalse(set(s["id"] for s in trials) & {e["key"] for e in r["tvbox.json"]["sites"]})
    def test_trial_approval_forbidden(self):
        with self.assertRaises(ValueError):
            self.build(site(status="trial"))
    def test_verified_trial_requires_matching_feedback(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        trials = [s for s in registry["sites"] if s["status"] == "trial_verified"]
        self.assertTrue(trials)
        s = dict(trials[0])
        for feedback in ({}, {**s["playback_feedback"], "upstream_ref": "wrong"},
                         {**s["playback_feedback"], "result": "fail"}):
            with self.subTest(feedback=feedback), self.assertRaises(ValueError):
                build({"sites": [{**s, "playback_feedback": feedback}]}, self.policy, deps)
    def test_verified_trial_not_formally_approved(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        s = next(s for s in registry["sites"] if s["status"] == "trial_verified")
        with self.assertRaises(ValueError):
            build({"sites": [{**s, "approved": True}]}, self.policy, deps)
    def test_user_failed_trial_excluded(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        result = build(registry, self.policy, deps)
        keys = {e["key"] for cfg in result.values() for e in cfg["sites"]}
        failed = [s for s in registry["sites"] if s.get("isolation_reason") == "user_reported_playback_failure"]
        self.assertTrue(failed)
        for s in failed:
            self.assertNotIn(s["id"], keys)
            self.assertFalse(s.get("health_managed"))
            self.assertTrue(s.get("reenable_requires_user_retest"))
    def test_verified_trial_prioritized(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        s = next(s for s in registry["sites"] if s["status"] == "trial_verified")
        new = {**s, "id": "fresh", "status": "trial", "playback_verified": False,
               "api": "https://example.com/new", "type": 1, "dependency_id": None, "trial_primary_for": [],
               "trial_entry": {"key":"fresh","name":s["name"],"type":1,"api":"https://example.com/new"}}
        result = build({"sites":[new,s]}, self.policy, deps)
        self.assertEqual([x["key"] for x in result["preview.json"]["sites"]], [s["id"],"fresh"])
    def test_preview_capacity_per_category(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        trials = [s for s in registry["sites"] if s["status"] in {"trial", "trial_verified"}]
        for category, limit in LIMITS.items():
            subset = [s for s in trials if category in s["categories"]]
            self.assertLessEqual(len(subset), limit)
            example = {"status":"trial","type":1,"dependency_id":None,"approved":False,
                       "playback_verified":False,"categories":[category],"name":"Fixture"}
            extra = [{**example, "id":f"fixture{i}", "api":f"https://example.com/{i}",
                      "trial_entry":{"key":f"fixture{i}","name":"Fixture","type":1,"api":f"https://example.com/{i}"}}
                     for i in range(limit + 1)]
            with self.subTest(category=category), self.assertRaisesRegex(ValueError, "Preview category limit exceeded"):
                build({"sites":extra}, self.policy, deps)
    def test_preview_policy_fixed(self):
        with self.assertRaises(ValueError):
            build({"sites":[]}, {**self.policy, "preview_category_limits":{"short":99}}, self.deps)
    def test_manual_isolation_cannot_be_reenabled_implicitly(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        s = next(s for s in registry["sites"] if s.get("reenable_requires_user_retest"))
        with self.assertRaisesRegex(ValueError, "Manual playback isolation"):
            build({"sites":[{**s, "status":"trial"}]}, self.policy, deps)
        with self.assertRaisesRegex(ValueError, "Manual playback isolation"):
            build({"sites":[{**s, "health_managed":True}]}, self.policy, deps)
    def test_playback_summary_matches_registry(self):
        registry = read("config/registry.json")
        summary = read("reports/health.json")["manual_playback"]
        feedback = {s["id"]:s["playback_feedback"]["result"] for s in registry["sites"] if "playback_feedback" in s}
        self.assertEqual(summary["tested"], len(feedback))
        self.assertEqual(summary["passed"], list(feedback.values()).count("ok"))
        self.assertEqual(summary["failed"], list(feedback.values()).count("fail"))
        self.assertEqual({k:v["result"] for k,v in summary["results"].items()}, feedback)
    def test_trial_ext_origin_only(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        s = next(s for s in registry["sites"] if s["id"] == "changzhang")
        result = build({"sites":[s]}, self.policy, deps)
        self.assertEqual(result["preview.json"]["sites"][0]["ext"], s["trial_entry"]["ext"])
        for bad in ["http://example.com", "https://example.com/path", "https://u:p@example.com", "https://example.com/?x=1", {"url":"https://example.com"}]:
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "Invalid trial ext"):
                build({"sites":[{**s, "trial_entry":{**s["trial_entry"],"ext":bad}}]}, self.policy, deps)
    def test_trial_pins_and_order(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        result = build(registry, self.policy, deps)
        pinned = {c:s["id"] for s in registry["sites"] for c in s.get("trial_primary_for", [])}
        self.assertEqual(set(pinned), set(LIMITS))
        expected = list(dict.fromkeys(pinned[c] for c in LIMITS))
        self.assertEqual([s["key"] for s in result["preview.json"]["sites"][:len(expected)]], expected)
    def test_trial_pin_rejects_unverified_and_duplicate(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        chosen = next(s for s in registry["sites"] if s.get("trial_primary_for"))
        c = chosen["trial_primary_for"][0]
        backup = next(s for s in registry["sites"] if s["status"] == "trial_verified"
                      and s["id"] != chosen["id"] and c in s["categories"])
        with self.assertRaisesRegex(ValueError, "Multiple trial primaries"):
            build({"sites":[chosen,{**backup,"trial_primary_for":[c]}]}, self.policy, deps)
        with self.assertRaisesRegex(ValueError, "Trial primary must be verified"):
            build({"sites":[{**chosen,"status":"trial","playback_verified":False}]}, self.policy, deps)
    def test_trial_primary_fallback(self):
        registry = read("config/registry.json")
        deps = read("config/dependencies.json")
        chosen = next(s for s in registry["sites"] if s.get("trial_primary_for"))
        c = chosen["trial_primary_for"][0]
        backup = next(s for s in registry["sites"] if s["status"] == "trial_verified"
                      and s["id"] != chosen["id"] and c in s["categories"])
        standby = {**backup,"trial_primary_for":[]}
        failed = {**chosen,"status":"isolated","playback_verified":False}
        result = build({"sites":[failed,standby]}, self.policy, deps)
        self.assertEqual([s["key"] for s in result["preview.json"]["sites"]], [standby["id"]])
    def test_wallpaper(self):
        self.assertTrue((ROOT/"assets/wallpaper.png").is_file())

class MaintenanceTests(unittest.TestCase):
    def test_failure_and_recovery(self):
        s = site()
        r = {}
        for i in range(1, 4):
            r = transition(s, r, "fail", f"2026-01-0{i}")
        self.assertEqual(s["status"], "isolated")
        r = transition(s, r, "ok", "2026-01-04")
        self.assertEqual(s["status"], "isolated")
        r = transition(s, r, "ok", "2026-01-05")
        self.assertEqual(s["status"], "active")
    def test_repeat_same_day(self):
        s = site()
        r = {}
        for i in range(4):
            r = transition(s, r, "fail", "2026-01-01")
        self.assertEqual(s["status"], "active")
        self.assertEqual(r["failure_days"], 1)
    def test_unknown(self):
        s = site()
        r = transition(s, {}, "fail", "2026-01-01")
        r = transition(s, r, "unknown", "2026-01-02")
        r = transition(s, r, "fail", "2026-01-03")
        self.assertEqual(s["status"], "active")
        self.assertEqual(r["failure_days"], 1)
    def test_manual_isolation(self):
        s = site(status="isolated")
        r = transition(s, {}, "ok", "2026-01-01")
        transition(s, r, "ok", "2026-01-02")
        self.assertEqual(s["status"], "isolated")
    def test_probe(self):
        def fake(url):
            if "ac=detail" in url:
                return "ok", {"list":[{"vod_id":1}]}
            if "ac=videolist" in url:
                return "ok", {"list":[{"vod_id":1}]}
            return "ok", {"class":[{"type_id":1}]}
        self.assertEqual(probe(site(), fake), "ok")
        self.assertEqual(probe(site(), lambda url: ("ok", {})), "fail")
        self.assertEqual(probe(site(), lambda url: ("unknown", None)), "unknown")
    def test_audit_no_import(self):
        config = {"upstreams":[{"id":"a", "audit_url":"https://raw.githubusercontent.com/a/b/main/x.json"}]}
        r = audit_upstreams(config, getter=lambda url: ("ok", {"sites":[{"type":3, "api":"secret"}],"spider":"unknown"}))
        self.assertEqual(r["a"]["types"], {"3":1})
        self.assertNotIn("secret", str(r))
    def test_audit_host_gate(self):
        with self.assertRaises(ValueError):
            audit_upstreams({"upstreams":[{"id":"a","audit_url":"https://example.com/x"}]})
    def test_bulk_loss_guard(self):
        before = {'sites':[site('one'),site('two')]}
        after = {'sites':[site('one',status='isolated'),site('two')]}
        self.assertTrue(mass_loss(before, after))
        self.assertFalse(mass_loss(before, before))
        self.assertFalse(mass_loss({'sites':[]}, before))
    def test_watch_fallback(self):
        result = build({"sites":[site("main", status="watch", primary_for=["series"]),site("backup")]}, read("config/policy.json"),read("config/dependencies.json"))
        self.assertEqual(result["sources/series.json"]["sites"][0]["key"], "backup")

if __name__ == "__main__":
    unittest.main(verbosity=2)
