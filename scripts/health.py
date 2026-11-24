"""P0 health status only. Network checks intentionally disabled."""
from sync import read
if __name__ == "__main__":
    if read("config/registry.json")["sites"]:
        raise SystemExit("Network health checks not implemented; cannot evaluate nonempty registry")
    print("NOT RUN: no approved sites; no network or playback verification performed")
