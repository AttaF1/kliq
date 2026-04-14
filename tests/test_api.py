from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

_SAMPLE_PAYLOAD = {
    "campaign_id": "CMP-9921",
    "brand_name": "Glow Beauty",
    "brand_industry": "Beauty & Cosmetics",
    "campaign_description": "Skincare launch in GCC.",
    "target_audience": {
        "age_range": [18, 34],
        "gender": "Female",
        "locations": ["Riyadh", "Jeddah", "Dubai", "Abu Dhabi"],
    },
    "content_requirements": {
        "platforms": ["Instagram", "TikTok"],
        "content_type": "Video Reel",
        "minimum_engagement_rate": 3.5,
    },
    "budget_range": {"min": 5000, "max": 15000, "currency": "SAR"},
}


def test_health():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["creators_loaded"] > 0


def test_match_sample_brief():
    payload = _SAMPLE_PAYLOAD
    with TestClient(app) as c:
        r = c.post("/match", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["campaign_id"] == "CMP-9921"
    assert data["total_creators_evaluated"] >= 1000
    assert len(data["matches"]) == 5
    for m in data["matches"]:
        assert "match_score" in m
        assert "score_breakdown" in m
        assert "match_reason" in m
        b = m["score_breakdown"]
        assert set(b.keys()) == {
            "niche_alignment",
            "audience_demographics",
            "platform_presence",
            "engagement_quality",
            "budget_fit",
        }


def test_match_401_when_api_key_required_but_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KLIQ_API_KEYS", "secret-one,other-key")
    with TestClient(app) as c:
        r = c.post("/match", json=_SAMPLE_PAYLOAD)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or missing API key"


def test_match_200_with_x_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KLIQ_API_KEYS", "secret-one,other-key")
    with TestClient(app) as c:
        r = c.post(
            "/match",
            json=_SAMPLE_PAYLOAD,
            headers={"X-API-Key": "secret-one"},
        )
    assert r.status_code == 200, r.text
    assert len(r.json()["matches"]) == 5


def test_match_multiline_campaign_description_still_ok():
    """Swagger/curl often emit real newlines inside quoted strings; middleware fixes."""
    p = dict(_SAMPLE_PAYLOAD)
    p["campaign_description"] = "line one\nline two"
    valid = json.dumps(p)
    # Turn JSON-escaped newlines in the payload into illegal raw newlines (Swagger mistake).
    broken = valid.replace("\\n", "\n").encode()
    with TestClient(app) as c:
        r = c.post(
            "/match",
            content=broken,
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["campaign_id"] == "CMP-9921"


def test_match_422_json_invalid_includes_hint():
    body = b"not valid json {"
    with TestClient(app) as c:
        r = c.post(
            "/match",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 422
    data = r.json()
    assert "hint" in data
    assert "JSON parse failed" in data["hint"]


def test_match_200_with_bearer_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KLIQ_API_KEYS", "my-bearer-token")
    with TestClient(app) as c:
        r = c.post(
            "/match",
            json=_SAMPLE_PAYLOAD,
            headers={"Authorization": "Bearer my-bearer-token"},
        )
    assert r.status_code == 200, r.text
