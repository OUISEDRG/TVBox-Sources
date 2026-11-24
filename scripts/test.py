import unittest
from sync import build, read, ROOT, BASE, LIMITS

def site(id="one", **kwargs):
    return dict(id=id, name=id, status="active", type=1, api="https://example.com/" + id,
                categories=["series"], primary_for=[], dependency_id=None, upstream="test fixture",
                authorization="synthetic test evidence", authorization_reviewed=True,
                security_reviewed=True, compatibility_reviewed=True, approved=True,
                playback_verified=True, score=90, **{}) | kwargs

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.policy = read("config/policy.json")
        self.deps = read("config/dependencies.json")
    def build(self, *sites):
        return build({"sites": list(sites)}, self.policy, self.deps)
    def test_limits(self):
        self.assertEqual(sum(LIMITS.values()), 26)
    def test_committed_outputs(self):
        for path, data in build(read("config/registry.json"), self.policy, self.deps).items():
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
    def test_wallpaper(self):
        self.assertTrue((ROOT/"assets/wallpaper.png").is_file())

if __name__ == "__main__":
    unittest.main(verbosity=2)
