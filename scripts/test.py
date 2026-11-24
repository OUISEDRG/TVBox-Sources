import unittest
from sync import build, read, ROOT
class InitialTests(unittest.TestCase):
    def setUp(self):
        self.registry = read("config/registry.json")
        self.policy = read("config/policy.json")
        self.deps = read("config/dependencies.json")
    def test_limits(self):
        self.assertEqual(sum(self.policy["categories"].values()),26)
    def test_outputs(self):
        result = build(self.registry,self.policy,self.deps)
        self.assertEqual(len(result),6)
        for path,data in result.items():
            self.assertEqual(read(path),data)
            self.assertEqual(data["sites"],[])
    def test_reject_unreviewed(self):
        with self.assertRaises(ValueError):
            build({"sites":[{"id":"unknown"}]}, self.policy,self.deps)
    def test_reject_dependency(self):
        with self.assertRaises(ValueError):
            build(self.registry,self.policy,{"dependencies":[{}]})
    def test_policy_change(self):
        with self.assertRaises(ValueError):
            build(self.registry,{**self.policy,"categories":{"short":99}},self.deps)
    def test_wallpaper(self):
        self.assertTrue((ROOT/"assets/wallpaper.png").is_file())
if __name__ == "__main__": unittest.main(verbosity=2)
