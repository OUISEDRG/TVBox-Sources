"""P0: local configuration builder; no network access or third-party execution."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))
def build(registry, policy, deps):
    if registry["sites"] or deps["dependencies"]:
        raise ValueError("P0 only supports an empty registry; implement and review P1 before admitting sites")
    if policy["categories"] != {"series": 8, "anime": 5, "movies": 8, "short": 5}:
        raise ValueError("Unexpected category policy")
    base = policy["base_url"]
    empty = {"sites": [], "parses": [], "lives": [], "wallpaper": base + "assets/wallpaper.png"}
    result = {"tvbox.json": empty, "preview.json": empty}
    result.update({f"sources/{name}.json": empty for name in policy["categories"]})
    return result
def main():
    result = build(read("config/registry.json"), read("config/policy.json"), read("config/dependencies.json"))
    for path, data in result.items():
        target = ROOT / path
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("P0 empty configurations generated; no playback source published")
if __name__ == "__main__":
    main()
