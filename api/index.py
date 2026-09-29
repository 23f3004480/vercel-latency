import json
import math
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


# Load telemetry data
DATA_FILE = Path(__file__).resolve().parent.parent / "q-vercel-latency.json"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    DATA = json.load(f)


class LatencyRequest(BaseModel):
    regions: list[str]
    threshold_ms: float


def percentile_95(values):
    if not values:
        return 0.0

    values = sorted(values)

    if len(values) == 1:
        return float(values[0])

    position = 0.95 * (len(values) - 1)

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return float(values[lower])

    fraction = position - lower

    return (
        values[lower]
        + fraction * (values[upper] - values[lower])
    )


@app.post("/api/latency")
def calculate_latency(request: LatencyRequest):

    results = []

    for region in request.regions:

        records = [
            row for row in DATA
            if row["region"] == region
        ]

        latencies = [
            float(row["latency_ms"])
            for row in records
        ]

        uptimes = [
            float(row["uptime_pct"])
            for row in records
        ]

        breaches = sum(
            1
            for latency in latencies
            if latency > request.threshold_ms
        )

        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            p95_latency = percentile_95(latencies)
            avg_uptime = sum(uptimes) / len(uptimes)
        else:
            avg_latency = 0.0
            p95_latency = 0.0
            avg_uptime = 0.0

        results.append({
            "region": region,
            "avg_latency": avg_latency,
            "p95_latency": p95_latency,
            "avg_uptime": avg_uptime,
            "breaches": breaches
        })

    return {
        "results": results
    }