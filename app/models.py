"""
I use a library called Pydantic to check if the JSON have all
    required fields? Are types correct (numbers vs text)?" and if something is wrong, FastAPI automatically returns an error (HTTP 422)
    before your business logic runs.

I am scoring math here, only structure and simple rules like "max budget must be >= min budget".
================================================================================
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TargetAudience(BaseModel):
    """
    matches the target_audience.
    """

    # Exactly two integers: [low_age, high_age] e.g. [18, 34]
    age_range: list[int] = Field(min_length=2, max_length=2)
    # Only one of these three strings is allowed (typo → validation error)
    gender: Literal["Female", "Male", "All"]
    # City names as a list of strings
    locations: list[str]

    @field_validator("age_range")
    @classmethod
    def valid_age_range(cls, v: list[int]) -> list[int]:

        lo, hi = v[0], v[1]
        if lo > hi:
            raise ValueError("age_range must be ordered low to high")
        return v


class ContentRequirements(BaseModel):
    """
    Check content_requirements.
    """

    platforms: list[str]
    content_type: str
    # ge=0.0 means "must be zero or positive"
    minimum_engagement_rate: float = Field(ge=0.0)


class BudgetRange(BaseModel):
    """
    Check budget_range.

    """

    min: int = Field(ge=0)
    max: int = Field(ge=0)
    currency: str

    @model_validator(mode="after")
    def max_gte_min(self) -> BudgetRange:
        """
        Runs after the whole BudgetRange object is built from JSON.
        """
        if self.max < self.min:
            raise ValueError("budget max must be >= min")
        return self


class CampaignMatchRequest(BaseModel):
    """
    Layman: Everything the matching engine needs in one package: who they are,
    what industry, who they target, platforms, budget, etc.
    """

    campaign_id: str
    brand_name: str
    brand_industry: str
    campaign_description: str
    # These three lines nest other models (objects inside the main object)
    target_audience: TargetAudience
    content_requirements: ContentRequirements
    budget_range: BudgetRange


class ScoreBreakdown(BaseModel):
    """
    Instead of one mystery number, I show points for niche, audience,
    platforms, engagement, and budget. They add up to match_score.
    """

    niche_alignment: float
    audience_demographics: float
    platform_presence: float
    engagement_quality: float
    budget_fit: float


class CreatorMatch(BaseModel):
    """
    ONE ROW in the matches list, a single creator with score + explanation.
    """

    creator_id: str
    creator_name: str
    match_score: float
    score_breakdown: ScoreBreakdown
    estimated_cost_sar: float
    match_reason: str


class MatchResponse(BaseModel):
    """
    THE FINAL JSON I send back to the client after POST /match.
    """

    campaign_id: str
    total_creators_evaluated: int
    matches: list[CreatorMatch]
