"""
Generates a synthetic delivery dataset for demos and manual testing,
since no real company dataset is wired in yet.

Usage:
    python data/generate_sample.py --n 50 --out data/sample_stops.json
"""

from __future__ import annotations

import argparse
import json
import random


def generate(n: int, center_lat: float, center_lon: float, spread: float, seed: int) -> dict:
    rng = random.Random(seed)
    stops = [
        {
            "id": f"stop_{i:03d}",
            "lat": round(center_lat + rng.uniform(-spread, spread), 6),
            "lon": round(center_lon + rng.uniform(-spread, spread), 6),
            "demand": rng.choice([1, 1, 1, 2, 3]),
        }
        for i in range(n)
    ]
    return {
        "company_id": "demo-co",
        "vehicles": max(2, n // 10),
        "vehicle_capacity": 15,
        "depot": {"lat": center_lat, "lon": center_lon},
        "stops": stops,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50, help="number of delivery stops")
    parser.add_argument("--lat", type=float, default=28.6139, help="center latitude (default: Delhi)")
    parser.add_argument("--lon", type=float, default=77.2090, help="center longitude")
    parser.add_argument("--spread", type=float, default=0.08, help="lat/lon jitter radius")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=str, default="data/sample_stops.json")
    args = parser.parse_args()

    payload = generate(args.n, args.lat, args.lon, args.spread, args.seed)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {args.n} stops to {args.out}")
