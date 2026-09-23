"""xFG prediction service.

POST /predict  scores a batch of shots: xFG (shooter-aware, when a known player code is given) and the
               context-only xFG for a league-average shooter, stamped with the model version.
GET  /health   liveness plus the active model version.
GET  /model    the model card summary and registry entry.

Every request is logged as one JSON line (request id, path, status, latency, batch size, model version) to
stdout and, if LOG_FILE is set, appended to that file.
"""
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from typing import List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from features import featurize  # noqa: E402

MODEL_PATH = os.environ.get("XFG_MODEL", os.path.join(ROOT, "model", "xfg_model.joblib"))
CARD_PATH = os.path.join(os.path.dirname(MODEL_PATH), "model_card.json")
REGISTRY_PATH = os.path.join(os.path.dirname(MODEL_PATH), "registry.json")
PRIOR_DECAY = 0.6
MAX_BATCH = 500

log = logging.getLogger("xfg")
log.setLevel(logging.INFO)
_h = logging.StreamHandler(sys.stdout); _h.setFormatter(logging.Formatter("%(message)s")); log.addHandler(_h)
if os.environ.get("LOG_FILE"):
    _f = logging.FileHandler(os.environ["LOG_FILE"]); _f.setFormatter(logging.Formatter("%(message)s")); log.addHandler(_f)

bundle = joblib.load(MODEL_PATH)
MODEL, FEATS, K = bundle["model"], bundle["features"], bundle["k_shrink"]
ZONES = bundle["categories"]["zone"]
CARD = json.load(open(CARD_PATH)) if os.path.exists(CARD_PATH) else {}
MODEL_SHA = hashlib.sha256(open(MODEL_PATH, "rb").read()).hexdigest()[:12]
VERSION = CARD.get("version", "unknown")
registry = json.load(open(REGISTRY_PATH)) if os.path.exists(REGISTRY_PATH) else {"models": []}
REG_ENTRY = next((m for m in registry["models"] if m.get("sha256", "").startswith(MODEL_SHA)), None)
effects_path = os.path.join(os.path.dirname(MODEL_PATH), f"shooter_effects_{bundle.get('trained_on', '')}.parquet")
EFFECTS = pd.read_parquet(effects_path).set_index("player") if os.path.exists(effects_path) else pd.DataFrame(columns=["n", "effect"])

app = FastAPI(title="Euroleague xFG", version=VERSION, description="Expected field-goal probability for Euroleague shots.")


class Shot(BaseModel):
    x: int = Field(..., ge=-800, le=800, description="cm, lateral, basket at 0")
    y: int = Field(..., ge=-200, le=1450, description="cm toward half court, basket at 0")
    pts: int = Field(..., description="2 or 3")
    minute: int = Field(1, ge=1, le=60, description="game minute (1-40, overtime above)")
    clock: str = Field("05:00", description="mm:ss left in the period")
    home: bool = True
    margin: float = Field(0.0, ge=-100, le=100, description="shooter's team margin before the shot")
    zone: Optional[str] = Field(None, description="league zone letter; inferred as unknown if omitted")
    player: Optional[str] = Field(None, description="league person code for the shooter effect, e.g. 002100")

    @field_validator("pts")
    @classmethod
    def _pts(cls, v):
        if v not in (2, 3):
            raise ValueError("pts must be 2 or 3")
        return v

    @field_validator("clock")
    @classmethod
    def _clock(cls, v):
        m, s = v.split(":")
        if not (0 <= int(m) <= 10 and 0 <= int(s) < 60):
            raise ValueError("clock must be mm:ss within a period")
        return v


class PredictRequest(BaseModel):
    shots: List[Shot] = Field(..., min_length=1, max_length=MAX_BATCH)


def shooter_term(code):
    if code is None or code not in EFFECTS.index:
        return 0.0
    r = EFFECTS.loc[code]
    return float(r.effect) * (float(r.n) + K) * PRIOR_DECAY / (float(r.n) * PRIOR_DECAY + K)


def score(shots):
    d = pd.DataFrame([{"x": s.x, "y": s.y, "pts": s.pts, "minute": s.minute, "clock": s.clock, "club": "H" if s.home else "A", "home": "H", "away": "A",
                        "score_home": 0, "score_away": 0, "made": 0, "zone": s.zone or "?", "fastbreak": 0, "second_chance": 0, "points_off_tov": 0} for s in shots])
    f = featurize(d)
    f["margin"] = [s.margin for s in shots]
    f["zone"] = pd.Categorical(f.zone.astype(str), categories=ZONES)
    if "shooter" in FEATS:
        f["shooter"] = [shooter_term(s.player) for s in shots]
        xfg = MODEL.predict_proba(f[FEATS])[:, 1]
        ctx = MODEL.predict_proba(f.assign(shooter=0.0)[FEATS])[:, 1]
    else:
        xfg = ctx = MODEL.predict_proba(f[FEATS])[:, 1]
    return xfg, ctx, f.dist.values


@app.middleware("http")
async def log_requests(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]; t0 = time.perf_counter()
    request.state.rid = rid
    try:
        response = await call_next(request)
    except Exception as e:
        log.info(json.dumps({"rid": rid, "path": request.url.path, "status": 500, "ms": round(1000 * (time.perf_counter() - t0), 1), "error": str(e), "model": VERSION}))
        return JSONResponse({"detail": "internal error", "rid": rid}, status_code=500)
    log.info(json.dumps({"rid": rid, "path": request.url.path, "status": response.status_code, "ms": round(1000 * (time.perf_counter() - t0), 1),
                         "n": getattr(request.state, "n", None), "model": VERSION}))
    response.headers["x-request-id"] = rid; response.headers["x-model-version"] = VERSION
    return response


@app.get("/health")
def health():
    return {"status": "ok", "model_version": VERSION, "model_sha256": MODEL_SHA, "trained_on": bundle.get("trained_on"), "shooter_effects": int(len(EFFECTS))}


@app.get("/model")
def model_card():
    return {"version": VERSION, "sha256": MODEL_SHA, "registry": REG_ENTRY, "card": {k: CARD.get(k) for k in ("trained_on", "n_shots", "n_shooters", "split", "features", "chosen", "metrics_test", "calibration_test", "algorithm")}}


@app.post("/predict")
def predict(req: PredictRequest, request: Request):
    request.state.n = len(req.shots)
    xfg, ctx, dist = score(req.shots)
    return {"model_version": VERSION, "n": len(req.shots),
            "predictions": [{"xfg": round(float(a), 4), "xfg_context": round(float(c), 4), "expected_points": round(float(a) * s.pts, 3), "distance_m": round(float(dm), 2),
                             "shooter_known": bool(s.player and s.player in EFFECTS.index)} for a, c, dm, s in zip(xfg, ctx, dist, req.shots)]}
