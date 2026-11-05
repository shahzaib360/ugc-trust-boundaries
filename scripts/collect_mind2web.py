"""Stream Mind2Web's training split into data/cache/mind2web (about 6 GB download)."""

from pathlib import Path

from ugcguard.measure import mind2web

n = mind2web.collect(Path("data/cache/mind2web"))
print(f"cached {n} tasks")
