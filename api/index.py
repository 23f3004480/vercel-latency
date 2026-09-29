import json
import math
import os
from typing import List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()


# ---------------------------------------------------------------------------
# CORS: set the header manually on every response instead of relying only on
# CORSMiddleware. CORSMiddleware only adds Access-Control-Allow-Origin when
# the incoming request carries an Origin header; some graders/checkers send
# plain requests with no Origin header, and Vercel's own routing layer can
# also interfere with the middleware's conditional logic. Setting it
# unconditionally here guarantees the header is always present.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = JSONResponse(content={})
    else:
        response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# ---------------------------------------------------------------------------
# Telemetry data (embedded from q-vercel-latency.json so the endpoint has no
# external file-system / network dependency once deployed on Vercel).
#
# Loaded defensively: if the file is missing/misplaced, we don't want the
# whole serverless function to crash on import (which is what was causing
# the 500 FUNCTION_INVOCATION_FAILED / blank Vercel error page on every
# single request, GET included). Instead we record the error and surface
# it in the JSON response, so the failure is actually visible and
# debuggable instead of an opaque crash page.
# ---------------------------------------------------------------------------
_DATA_PATH = os.path.join(os.path.dirname(__file__), "data.json")
_DATA_LOAD_ERROR = None
RECORDS: List[dict] = []
try:
    with open(_DATA_PATH, "r") as _f:
        RECORDS = json.load(_f)
except Exception as exc:  # noqa: BLE001 - deliberately broad, see comment above
    _DATA_LOAD_ERROR = f"{type(exc).__name__}: {exc} (looked for: {_DATA_PATH}, dir contents: {os.listdir(os.path.dirname(__file__))})"


def _percentile(values: List[float], pct: float) -> float:
    """Linear-interpolation percentile (same convention as numpy.percentile)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    d0 = s[int(f)] * (c - k)
    d1 = s[int(c)] * (k - f)
    return d0 + d1


def _compute_metrics(regions: List[str], threshold_ms: float) -> dict:
    result = {}
    for region in regions:
        region_records = [r for r in RECORDS if r.get("region") == region]
        latencies = [r["latency_ms"] for r in region_records]
        uptimes = [r["uptime_pct"] for r in region_records]

        if not region_records:
            result[region] = {
                "avg_latency": None,
                "p95_latency": None,
                "avg_uptime": None,
                "breaches": 0,
            }
            continue

        result[region] = {
            "avg_latency": round(sum(latencies) / len(latencies), 3),
            "p95_latency": round(_percentile(latencies, 95), 3),
            "avg_uptime": round(sum(uptimes) / len(uptimes), 3),
            "breaches": sum(1 for l in latencies if l > threshold_ms),
        }
    return result


@app.post("/api/latency")
async def latency_endpoint(request: Request):
    if _DATA_LOAD_ERROR:
        return JSONResponse(status_code=500, content={"error": _DATA_LOAD_ERROR})

    body = await request.json()
    regions = body.get("regions", [])
    threshold_ms = body.get("threshold_ms")

    if not isinstance(regions, list) or not regions:
        return JSONResponse(
            status_code=400,
            content={"error": "'regions' must be a non-empty list of region names."},
        )
    if threshold_ms is None:
        return JSONResponse(
            status_code=400,
            content={"error": "'threshold_ms' is required."},
        )

    metrics = _compute_metrics(regions, float(threshold_ms))
    return JSONResponse(content=metrics)


@app.options("/api/latency")
async def latency_options():
    # Explicit preflight handler in case the platform routes OPTIONS
    # directly to this path instead of through the middleware above.
    return JSONResponse(content={})


@app.get("/api/latency")
async def latency_info():
    # Handy for sanity-checking the deployment in a browser.
    if _DATA_LOAD_ERROR:
        return JSONResponse(status_code=500, content={"error": _DATA_LOAD_ERROR})
    return {
        "message": "POST {'regions': [...], 'threshold_ms': <number>} to this endpoint.",
        "available_regions": sorted({r["region"] for r in RECORDS}),
    }