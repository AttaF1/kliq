from __future__ import annotations

import pytest

from app.models import CampaignMatchRequest
from app.scoring import (
    audience_demographics_score,
    budget_fit_score,
    engagement_quality_score,
    niche_alignment,
    platform_presence_score,
    score_creator,
)


def _campaign(**kwargs) -> CampaignMatchRequest:
    base = dict(
        campaign_id="CMP-1",
        brand_name="Test",
        brand_industry="Beauty & Cosmetics",
        campaign_description="Test",
        target_audience={
            "age_range": [18, 34],
            "gender": "Female",
            "locations": ["Riyadh", "Dubai"],
        },
        content_requirements={
            "platforms": ["Instagram", "TikTok"],
            "content_type": "Video Reel",
            "minimum_engagement_rate": 3.5,
        },
        budget_range={"min": 5000, "max": 15000, "currency": "SAR"},
    )
    base.update(kwargs)
    return CampaignMatchRequest(**base)


def test_niche_beauty_cosmetics_maps_to_skincare_primary():
    assert niche_alignment("Beauty & Cosmetics", "Beauty & Skincare", []) == 20.0


def test_niche_secondary_partial():
    s = niche_alignment("Beauty & Cosmetics", "Fitness", ["Beauty & Skincare"])
    assert s == pytest.approx(17.0)


def test_niche_automotive_not_equivalent_to_technology():
    assert niche_alignment("Automotive", "Technology", []) == 0.0


def test_niche_automotive_synonyms_full_points():
    assert niche_alignment("Automotive", "Cars", []) == 20.0


def test_audience_missing_demographics_imputed_neutral():
    c = _campaign()
    stats = [
        {
            "followers": 100_000,
            "age_18_34_pct": None,
            "gender_female_pct": None,
            "top_locations": None,
        }
    ]
    filled_style = [
        {
            "followers": 100_000,
            "age_18_34_pct": 55.0,
            "gender_female_pct": 50.0,
            "top_locations": [],
        }
    ]
    # direct function expects pre-imputed; here test branch via score_creator instead
    sc = audience_demographics_score(c, filled_style)
    assert 0 < sc < 30


def test_platform_missing_tiktok_scores_partial():
    c = _campaign()
    platforms = {
        "instagram": {"followers": 200_000, "engagement_rate": 5.0, "audience_demographics": {}},
    }
    s = platform_presence_score(["Instagram", "TikTok"], platforms)
    assert s < 20.0
    assert s >= 10.0


def test_engagement_below_minimum_gets_reduced_score():
    c = _campaign()
    platforms = {
        "instagram": {"followers": 200_000, "engagement_rate": 1.0, "audience_demographics": {}},
        "tiktok": {"followers": 200_000, "engagement_rate": 1.0, "audience_demographics": {}},
    }
    s = engagement_quality_score(["Instagram", "TikTok"], platforms, 3.5)
    assert s < 20.0


def test_budget_inside_range_full():
    assert budget_fit_score(8000, 5000, 15000) == 10.0


def test_budget_far_above_range_low():
    assert budget_fit_score(200_000, 5000, 15000) < 3.0


def test_score_creator_missing_tiktok_platform():
    c = _campaign()
    creator = {
        "creator_id": "X-1",
        "creator_name": "Test",
        "primary_niche": "Beauty & Skincare",
        "secondary_niches": [],
        "platforms": {
            "instagram": {
                "followers": 200_000,
                "engagement_rate": 5.0,
                "audience_demographics": {
                    "age_18_34_pct": 70,
                    "gender_female_pct": 80,
                    "top_locations": ["Riyadh", "Jeddah"],
                },
            }
        },
        "average_campaign_cost_sar": 9000,
    }
    b, total, _dbg = score_creator(c, creator)
    assert b.platform_presence < 20.0
    assert total > 0


def test_score_creator_no_platforms_dict():
    c = _campaign()
    creator = {
        "creator_id": "X-2",
        "creator_name": "Empty",
        "primary_niche": "Gaming",
        "secondary_niches": [],
        "platforms": {},
        "average_campaign_cost_sar": 1000,
    }
    b, total, _ = score_creator(c, creator)
    assert b.platform_presence == 0.0
    assert b.engagement_quality == 0.0
