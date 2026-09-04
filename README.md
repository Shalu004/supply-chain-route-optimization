# RouteOpt — Supply Chain Route Optimization Engine

Clusters delivery stops into vehicle zones, optimizes the visiting order
within each zone, and reports the cost savings versus an unoptimized
baseline. Exposed as a REST API so it can be integrated into a dashboard
or another system, not just run from a notebook.

## Results on a sample dataset

Running the included 40-stop synthetic dataset (`data/generate_sample.py`)
through the full pipeline:

| Metric | Baseline (naive) | Optimized | Improvement |
|---|---|---|---|
| Total distance | 331.0 km | 106.6 km | -67.8% |
| Total cost | $497.91 | $295.92 | **-40.6%** |
| Vehicles used | 4 | 4 | (same fleet size — fair comparison) |

The baseline uses the **same number of vehicles** as the optimized run —
it just assigns stops in received order with no clustering and no route
optimization. This matters: an unfair baseline (e.g. one vehicle vs four)
would inflate the improvement number by hiding a fleet-size difference
inside what should be a routing-quality comparison.

Numbers will vary with your own data — regenerate with
`python data/generate_sample.py --n <count>` and re-run.

## Architecture

```
src/routeopt/          Framework-agnostic optimization engine
  clustering.py         K-Means zone assignment + capacity rebalancing
  routing.py             Nearest-neighbor + 2-opt route sequencing
  pipeline.py             Orchestration + baseline cost comparison

api/                    Thin REST wrapper around the engine
  app.py                  Flask routes (see docs/ for FastAPI port)
  schemas.py              Request validation

tests/test_engine.py   14 tests covering clustering, routing, pipeline

data/generate_sample.py Synthetic dataset generator for demos

docker/, docker-compose.yml   Containerized deployment
.github/workflows/ci.yml      Runs the test suite on every push
docs/PORTING_TO_PRODUCTION.md Exact steps to swap in OR-Tools/FastAPI
```

**Design principle:** the engine (`src/routeopt/`) has zero dependency on
the web framework. It's a plain, testable Python package. The API layer
is a thin wrapper on top. This is what makes it possible to later run the
same engine behind a job queue (Celery), a different framework, or a CLI
— without touching the optimization logic.

## Honesty about this build

This was built in a sandboxed environment with **no internet access**, so
two substitutions were made from what a real production system should
use:

| This build uses | Production should use | Why |
|---|---|---|
| Flask | FastAPI | Async, auto-generated OpenAPI docs, better performance under load |
| Custom NetworkX/SciPy 2-opt heuristic | Google OR-Tools | Handles multi-vehicle capacity, time windows, and pickup/delivery pairing natively; scales to far larger stop counts |
| In-memory dict for run history | PostgreSQL + PostGIS with Row-Level Security | The in-memory store is **not** real multi-tenant isolation — it has no persistence and no access control |

`requirements.txt` has both sets of packages, with the production ones
commented out (they need internet to install). `docs/PORTING_TO_PRODUCTION.md`
has the exact swap steps — both are drop-in replacements against the
existing interfaces, not rewrites.

## Setup

```bash
pip install -r requirements.txt

# Run the test suite
python -m pytest tests/ -v
# or: python -m unittest tests.test_engine -v

# Generate a sample dataset
python data/generate_sample.py --n 40 --out data/sample_stops.json

# Run the API
python api/app.py
# API now live at http://localhost:8000
```

### Try it

```bash
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d @data/sample_stops.json
```

### With Docker

```bash
docker compose up --build
```
*(Not verified in this sandbox — no Docker available here. Standard
Dockerfile/compose patterns, but test on your machine before relying on it.)*

## API

**POST /optimize**
```json
{
  "company_id": "acme-corp",
  "vehicles": 3,
  "vehicle_capacity": 20,
  "depot": {"lat": 28.61, "lon": 77.20},
  "stops": [
    {"id": "s1", "lat": 28.615, "lon": 77.205, "demand": 1}
  ]
}
```
Returns optimized routes per vehicle zone, distance, cost, and the
baseline comparison.

**GET /health** — liveness check
**GET /companies/{company_id}/runs** — past run summaries (demo store,
non-persistent)

## What's genuinely done vs. what's still a stub

**Done and tested:**
- Clustering + capacity-aware rebalancing
- Route sequencing with a real optimization pass (2-opt), verified to
  never produce a worse route than the naive input order
- Honest baseline comparison (same fleet size, fair accounting)
- Working REST API with input validation and error handling
- 14 passing unit/integration tests
- CI pipeline

**Explicitly a stub, not done:**
- Multi-tenancy is a bare dict, not database-enforced isolation
- No authentication — `company_id` is trusted from the request body
- No billing, no frontend dashboard, no persistent storage
- Docker setup is written but unverified in this environment

See `docs/PORTING_TO_PRODUCTION.md` and the earlier roadmap for the
remaining steps (auth, database, dashboard, billing, deployment).
