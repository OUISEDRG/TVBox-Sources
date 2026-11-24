"""Health status placeholder. Never claim unperformed network or playback tests."""
from sync import read
if __name__ == "__main__":
    sites = read("config/registry.json")["sites"]
    print(f"NOT RUN: {len(sites)} registered sites; no network or playback verification performed")
