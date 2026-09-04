# Porting to production-grade libraries

This project was built inside a sandbox with no internet access, so it
uses **Flask** and a **NetworkX/SciPy-based TSP heuristic** instead of the
libraries recommended for real deployment: **FastAPI** and **Google
OR-Tools**. Both swaps are drop-in replacements against the same
interfaces already in this codebase. This doc is the exact checklist.

## 1. Swap the routing engine for OR-Tools

Replace `src/routeopt/routing.py`'s `solve_route()` internals with a call
to `ortools.constraint_solver.pywrapcp.RoutingModel`. Keep the function
signature identical:

```python
def solve_route(zone_id: int, stops: list[Stop], depot: Stop | None = None) -> Route:
    ...
```

Why bother switching: OR-Tools natively supports multi-vehicle capacity
constraints, delivery time windows, and pickup/delivery pairing, and its
solver scales to hundreds of stops far better than the 2-opt heuristic
here (which is fine for demos, not for a 500-stop production run).

Install: `pip install ortools`

## 2. Swap Flask for FastAPI

`api/app.py` is deliberately thin — each route handler just validates
input, calls the engine, and serializes output. Porting means:

- Replace `schemas.py`'s manual validation with `pydantic.BaseModel`
  classes (`OptimizeRequest`, `OptimizeResponse`) using the same field
  names already used here.
- Replace `@app.route(..., methods=["POST"])` with `@app.post(...)`.
- Replace `request.get_json()` / `jsonify()` with typed request/response
  models — FastAPI handles serialization automatically.
- You get OpenAPI docs at `/docs` for free.

Install: `pip install fastapi uvicorn[standard] pydantic`

## 3. Replace the in-memory run store with PostgreSQL + PostGIS

`_RUN_STORE` in `api/app.py` is explicitly a non-persistent, non-isolated
placeholder. Before any real multi-company use:

- Stand up PostgreSQL with the PostGIS extension.
- Add a `company_id` column to every table and enable Row-Level Security
  so tenant isolation is enforced by the database, not application code.
- Persist stops, runs, and routes instead of holding them in a dict.

## 4. Add authentication

Wire in Clerk or Auth0 so every request resolves to a `company_id`
instead of trusting a client-supplied field in the JSON body (the current
demo API trusts `company_id` from the request, which is fine for a solo
demo and unsafe for anything multi-tenant).
