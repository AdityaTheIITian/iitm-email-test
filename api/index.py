import json
import math
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

app = FastAPI()


@app.middleware("http")
async def cors(request: Request, call_next):
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            },
        )

    response = await call_next(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

    return response


DATA_PATH = Path(__file__).parent / "telemetry.json"


def _load():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list):
                raw = v
                break

    return raw


def _pick(rec, names):
    for n in names:
        if n in rec and rec[n] is not None:
            return float(rec[n])
    return None


RECORDS = []

for r in _load():
    lat = _pick(
        r,
        ["latency_ms", "latency", "latencyMs"],
    )

    up = _pick(
        r,
        ["uptime_pct", "uptime", "uptime_percent", "uptimePct"],
    )

    reg = r.get("region")

    if reg is not None and lat is not None:
        RECORDS.append(
            {
                "region": str(reg),
                "latency": lat,
                "uptime": up,
            }
        )


def percentile(values, p):
    s = sorted(values)

    k = (len(s) - 1) * p / 100
    lo = math.floor(k)
    hi = math.ceil(k)

    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Query(BaseModel):
    regions: List[str]
    threshold_ms: float


@app.get("/{path:path}")
def health(path: str = ""):
    return {
        "status": "ok",
        "usage": "POST {regions:[...], threshold_ms:180}",
    }


@app.post("/{path:path}")
def metrics(q: Query, path: str = ""):
    out = {}

    for region in q.regions:
        rows = [
            r
            for r in RECORDS
            if r["region"] == region
        ]

        if not rows:
            out[region] = {
                "avg_latency": None,
                "p95_latency": None,
                "avg_uptime": None,
                "breaches": 0,
            }
            continue

        lats = [
            r["latency"]
            for r in rows
        ]

        ups = [
            r["uptime"]
            for r in rows
            if r["uptime"] is not None
        ]

        out[region] = {
            "avg_latency": round(
                sum(lats) / len(lats),
                4,
            ),
            "p95_latency": round(
                percentile(lats, 95),
                4,
            ),
            "avg_uptime": (
                round(sum(ups) / len(ups), 4)
                if ups
                else None
            ),
            "breaches": sum(
                1
                for x in lats
                if x > q.threshold_ms
            ),
        }

    return {
        **out,
        "regions": out,
    }