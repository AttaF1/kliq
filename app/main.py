"""
This is the web server layer.

  It starts FastAPI.
  On startup it loads all creators from a JSON file into memory.
  It exposes:
      GET  /health
      POST /match

It calls score_creator() from scoring.py for each creator, sorts results,
and returns JSON.
================================================================================
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import auth_enabled, verify_api_key_dependency
from app.middleware import MatchJsonBodySanitizeMiddleware
from app.models import CampaignMatchRequest, CreatorMatch, MatchResponse
from app.scoring import build_match_reason, score_creator

# ------------------------------------------------------------------------------
# Logging: print messages with time + level (INFO, ERROR, DEBUG) to the console.
# LOG_LEVEL=DEBUG shows one line per creator (verbose).
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# Path to creators JSON: folder "data" next to the project root (see folder layout).
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "creators_database.json"
# Docker can set CREATORS_DB_PATH to point somewhere else.
CREATORS_PATH = Path(os.environ.get("CREATORS_DB_PATH", str(DEFAULT_DB)))

# Global list: all creator dicts loaded once. Empty until _load_creators() runs.
_creators: list[dict] = []


def _load_creators() -> None:
    """
    Read creators_database.json and fill the global _creators list.

    """
    global _creators
    if not CREATORS_PATH.is_file():
        logger.error("Creators database not found at %s", CREATORS_PATH)
        _creators = []
        return
    with CREATORS_PATH.open(encoding="utf-8") as f:
        _creators = json.load(f)
    logger.info("Loaded %s creators from %s", len(_creators), CREATORS_PATH)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Before accepting any HTTP request, load creators once and run the server
    """
    _load_creators()
    if auth_enabled():
        logger.info("API key auth enabled for POST /match (KLIQ_API_KEYS)")
    else:
        logger.warning(
            "API key auth disabled — set KLIQ_API_KEYS for production (comma-separated)"
        )
    yield


# The FastAPI application object — routes are registered on `app` below.
app = FastAPI(
    title="Kliq Creator Matching Engine",
    description="Part 2 case study — brand brief vs creator pool, top 5 matches.",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(MatchJsonBodySanitizeMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    payload: dict = {"detail": errors}
    if any(e.get("type") == "json_invalid" for e in errors):
        payload["hint"] = (
            "JSON parse failed. If you pasted multi-line text inside a string, "
            "POST /match usually auto-fixes that; otherwise use one line or \\n. "
            "For non-JSON bodies, send Content-Type: application/json with valid JSON."
        )
    return JSONResponse(status_code=422, content=payload)


@app.get("/health")
def health() -> dict:
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "creators_loaded": len(_creators)}


@app.post(
    "/match",
    response_model=MatchResponse,
    dependencies=[Depends(verify_api_key_dependency)],
)
def match_campaign(campaign: CampaignMatchRequest) -> MatchResponse:
    """
    Main business endpoint from the case study PDF.
    """
    if not _creators:
        raise HTTPException(status_code=503, detail="Creators database not loaded")

    # Will hold one CreatorMatch object per creator (before we sort and slice).
    results: list[CreatorMatch] = []

    for creator in _creators:
        # score_creator returns: (five sub-scores as object, total, debug dict for logs)
        breakdown, total, dbg = score_creator(campaign, creator)

        # Optional deep logging — only visible if LOG_LEVEL=DEBUG
        logger.debug(
            "creator=%s total=%s niche=%s audience=%s platform=%s engagement=%s budget=%s meta=%s",
            dbg.get("creator_id"),
            total,
            breakdown.niche_alignment,
            breakdown.audience_demographics,
            breakdown.platform_presence,
            breakdown.engagement_quality,
            breakdown.budget_fit,
            dbg,
        )

        # Typical cost for display; bad/missing values → 0.0 so the API never crashes
        raw_cost = creator.get("average_campaign_cost_sar")
        try:
            estimated = float(raw_cost) if raw_cost is not None else 0.0
        except (TypeError, ValueError):
            estimated = 0.0

        results.append(
            CreatorMatch(
                creator_id=str(creator.get("creator_id", "")),
                creator_name=str(creator.get("creator_name", "")),
                match_score=total,
                score_breakdown=breakdown,
                estimated_cost_sar=estimated,
                match_reason=build_match_reason(campaign, creator, breakdown),
            )
        )

    # `key=lambda m: m.match_score` means "sort by this attribute"
    # `reverse=True` means highest score first
    results.sort(key=lambda m: m.match_score, reverse=True)
    top_five = results[:5]  # first 5 elements (Python slice)

    # One INFO line per request — enough for operators without spamming logs
    logger.info(
        "match campaign_id=%s evaluated=%s top_score=%s",
        campaign.campaign_id,
        len(_creators),
        top_five[0].match_score if top_five else None,
    )

    return MatchResponse(
        campaign_id=campaign.campaign_id,
        total_creators_evaluated=len(_creators),
        matches=top_five,
    )
