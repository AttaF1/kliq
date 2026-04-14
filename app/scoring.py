"""
Rule-based creator–brand matching (Kliq Part 2).

Computes five capped scores (30 + 20 + 20 + 20 + 10 ≈ 100), returns breakdown + text.
Pure functions — no I/O or logging (see main.py). Details are in ARCHITECTURE.md.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from app.models import CampaignMatchRequest, ScoreBreakdown

# PDF-style weight caps (points out of 100)
MAX_AUDIENCE = 30.0
MAX_NICHE = 20.0
MAX_PLATFORM = 20.0
MAX_ENGAGEMENT = 20.0
MAX_BUDGET = 10.0

PLATFORM_KEY_MAP: dict[str, str] = {
    "instagram": "instagram",
    "tiktok": "tiktok",
    "youtube": "youtube",
}


def _norm_label(s: str) -> str:
    t = s.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t.replace(" and ", " & ")


# Synonym groups (each inner tuple is one equivalence class). All labels are normalized
# with _norm_label so matching is case-insensitive. Automotive is NOT merged with Tech.
_RAW_NICHE_EQUIVALENCE: tuple[tuple[str, ...], ...] = (
    ("beauty & skincare", "beauty & cosmetics"),
    ("food & beverage", "food & drink", "f&b"),
    ("technology", "tech", "it"),
    ("automotive", "auto", "cars", "vehicles", "motor vehicles"),
    ("fashion", "clothing", "apparel", "fashion & apparel"),
    ("gaming", "games", "game", "game development"),
    ("travel", "tourism", "tourist", "travel & tourism"),
    ("health & fitness", "health & wellbeing", "health & well-being", "wellness", "fitness"),
    ("home & garden", "home & decor", "home decor", "garden"),
    ("sports", "sports & fitness", "sports & recreation"),
    ("education technology", "edtech"),
    ("education", "learning", "e-learning"),
    ("home & living", "home living", "living"),
    ("consumer electronics", "electronics", "consumer electronics & technology"),
    ("pet care", "pet", "pet products", "pet supplies"),
    ("financial services", "finance", "financial"),
)

NICHE_EQUIVALENCE_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(_norm_label(x) for x in group) for group in _RAW_NICHE_EQUIVALENCE
)


def _tokens(s: str) -> set[str]:
    return {x for x in re.split(r"[^a-z0-9]+", _norm_label(s)) if len(x) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


def _same_niche_group(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in g and b in g for g in NICHE_EQUIVALENCE_GROUPS)


def _niche_points_from_jaccard(j: float, scale: float) -> float:
    if j <= 0:
        return 0.0
    return min(MAX_NICHE * scale, MAX_NICHE * scale * (0.35 + 0.65 * j))


def niche_alignment(brand_industry: str, primary_niche: str, secondary_niches: list[str]) -> float:
    """Niche & industry vs creator niches; max MAX_NICHE (synonym groups, then word overlap)."""
    brand_n = _norm_label(brand_industry)
    primary_n = _norm_label(primary_niche)
    secondary_ns = [_norm_label(x) for x in secondary_niches]

    if _same_niche_group(brand_n, primary_n):
        return MAX_NICHE
    if any(_same_niche_group(brand_n, s) for s in secondary_ns):
        return MAX_NICHE * 0.85

    brand_tok, primary_tok = _tokens(brand_industry), _tokens(primary_niche)
    if brand_tok and primary_tok:
        j = _jaccard(brand_tok, primary_tok)
        if j > 0:
            return _niche_points_from_jaccard(j, 1.0)

    best_j = 0.0
    for raw_sec in secondary_niches:
        sec_tok = _tokens(raw_sec)
        if sec_tok:
            best_j = max(best_j, _jaccard(brand_tok, sec_tok))
    return _niche_points_from_jaccard(best_j, 0.75) if best_j > 0 else 0.0


def _age_overlap_18_34(lo: int, hi: int) -> float:
    a, b = max(lo, 18), min(hi, 34)
    if b < a:
        return 0.0
    overlap = float(b - a + 1)
    span = float(max(hi - lo + 1, 1))
    return min(1.0, overlap / span)


def _location_hit_ratio(targets: list[str], tops: list[str] | None) -> float:
    if not targets:
        return 1.0
    if not tops:
        return 0.0
    want = {_norm_label(c) for c in targets}
    have = {_norm_label(c) for c in tops}
    hits = 0
    for city in want:
        if city in have:
            hits += 1
        elif any(len(city) > 3 and len(h) > 3 and (city in h or h in city) for h in have):
            hits += 1
    return min(1.0, hits / len(want))


def _avg_by_followers(rows: list[dict[str, Any]], field: str) -> float:
    tw = sum(int(r.get("followers") or 0) for r in rows)
    if tw <= 0:
        n = max(len(rows), 1)
        return sum(float(r.get(field) or 0) for r in rows) / n
    return sum(float(r.get(field) or 0) * int(r.get("followers") or 0) for r in rows) / tw


def audience_demographics_score(
    campaign: CampaignMatchRequest,
    platform_rows: list[dict[str, Any]],
) -> float:
    """Audience fit vs brief (age/gender/cities); max MAX_AUDIENCE."""
    if not platform_rows:
        return 0.0

    ta = campaign.target_audience
    mult = _age_overlap_18_34(ta.age_range[0], ta.age_range[1])
    age_pct = _avg_by_followers(platform_rows, "age_18_34_pct")
    female_pct = _avg_by_followers(platform_rows, "gender_female_pct")

    age_pts = mult * (age_pct / 100.0) * 10.0
    if ta.gender == "Female":
        gender_pts = (female_pct / 100.0) * 10.0
    elif ta.gender == "Male":
        gender_pts = ((100.0 - female_pct) / 100.0) * 10.0
    else:
        gender_pts = 10.0

    with_locs = [r for r in platform_rows if r.get("top_locations") is not None]
    if with_locs:
        loc_pts = (
            sum(_location_hit_ratio(ta.locations, r.get("top_locations")) for r in with_locs)
            / len(with_locs)
            * 10.0
        )
    else:
        loc_pts = 0.0

    return min(MAX_AUDIENCE, age_pts + gender_pts + loc_pts)


def _brief_platform_keys(labels: list[str], *, mapped_only: bool = False) -> list[str]:
    """Map brief names to JSON keys. If mapped_only, drop unknown platforms (for audience rows)."""
    out: list[str] = []
    for lab in labels:
        k = lab.strip().lower()
        if mapped_only:
            if k in PLATFORM_KEY_MAP:
                out.append(PLATFORM_KEY_MAP[k])
        else:
            out.append(PLATFORM_KEY_MAP.get(k, k))
    return out


def _platform_payloads(creator_platforms: dict[str, Any], keys: list[str]) -> Iterator[dict[str, Any]]:
    """Yield creator platform dicts for each key that exists and is a dict."""
    for pk in keys:
        pdata = creator_platforms.get(pk)
        if isinstance(pdata, dict):
            yield pdata


def platform_presence_score(
    brief_platforms: list[str],
    creator_platforms: dict[str, Any],
    min_followers: int = 10_000,
) -> float:
    """Required platforms + follower reach; max MAX_PLATFORM."""
    if not brief_platforms:
        return MAX_PLATFORM

    keys = _brief_platform_keys(brief_platforms)
    share = MAX_PLATFORM / len(keys)
    cap = max(min_followers * 5, 1)
    total = 0.0
    for pdata in _platform_payloads(creator_platforms, keys):
        followers = int(pdata.get("followers") or 0)
        if followers <= 0:
            continue
        r = min(1.0, followers / cap)
        total += share * (0.5 + 0.5 * r)
    return min(MAX_PLATFORM, total)


def engagement_quality_score(
    brief_platforms: list[str],
    creator_platforms: dict[str, Any],
    minimum_rate: float,
) -> float:
    """Engagement vs brief minimum per platform; max MAX_ENGAGEMENT."""
    if not brief_platforms:
        return MAX_ENGAGEMENT

    keys = _brief_platform_keys(brief_platforms)
    share = MAX_ENGAGEMENT / len(keys)
    denom = max(minimum_rate, 0.1)
    total = 0.0
    for pdata in _platform_payloads(creator_platforms, keys):
        rate = float(pdata.get("engagement_rate") or 0.0)
        if minimum_rate <= 0:
            total += share
        elif rate >= minimum_rate:
            bonus = min(1.0, (rate - minimum_rate) / denom)
            total += share * (0.65 + 0.35 * bonus)
        else:
            total += share * max(0.0, rate / minimum_rate) * 0.45
    return min(MAX_ENGAGEMENT, total)


def budget_fit_score(cost: float | None, budget_min: int, budget_max: int) -> float:
    """Typical cost vs budget band; max MAX_BUDGET."""
    if cost is None:
        return MAX_BUDGET * 0.35
    c = float(cost)
    if budget_min <= c <= budget_max:
        return MAX_BUDGET
    if c < budget_min and budget_min > 0:
        ratio = c / budget_min
        return MAX_BUDGET * (0.55 + 0.45 * ratio) if ratio >= 0.5 else MAX_BUDGET * ratio
    if c > budget_max:
        over = c - budget_max
        span = max(budget_max, 1)
        penalty = min(1.0, over / span)
        return MAX_BUDGET * max(0.0, 1.0 - 0.85 * penalty)
    return 0.0


def _audience_rows(creator_platforms: dict[str, Any], required_keys: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pk in required_keys:
        pdata = creator_platforms.get(pk)
        if not isinstance(pdata, dict):
            continue
        demo = pdata.get("audience_demographics")
        followers = int(pdata.get("followers") or 0)
        if not isinstance(demo, dict):
            rows.append(
                {
                    "followers": followers,
                    "age_18_34_pct": None,
                    "gender_female_pct": None,
                    "top_locations": None,
                }
            )
        else:
            rows.append(
                {
                    "followers": followers,
                    "age_18_34_pct": demo.get("age_18_34_pct"),
                    "gender_female_pct": demo.get("gender_female_pct"),
                    "top_locations": demo.get("top_locations"),
                }
            )
    return rows


def _impute_demographics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filled: list[dict[str, Any]] = []
    for r in rows:
        age, gen, locs = r.get("age_18_34_pct"), r.get("gender_female_pct"), r.get("top_locations")
        filled.append(
            {
                "followers": r.get("followers") or 0,
                "age_18_34_pct": 55.0 if age is None else float(age),
                "gender_female_pct": 50.0 if gen is None else float(gen),
                "top_locations": locs if locs else [],
            }
        )
    return filled


def score_creator(
    campaign: CampaignMatchRequest,
    creator: dict[str, Any],
) -> tuple[ScoreBreakdown, float, dict[str, Any]]:
    """Score one creator: five dimensions, rounded breakdown, total, debug dict for logs."""
    raw = creator.get("platforms")
    platforms: dict[str, Any] = raw if isinstance(raw, dict) else {}

    req = _brief_platform_keys(campaign.content_requirements.platforms, mapped_only=True)
    raw_rows = _audience_rows(platforms, req)
    missing_demo = bool(req) and any(
        not isinstance(platforms.get(k), dict)
        or not isinstance((platforms.get(k) or {}).get("audience_demographics"), dict)
        for k in req
    )

    if raw_rows:
        audience_rows = _impute_demographics(raw_rows)
    else:
        fb_keys = [k for k, v in platforms.items() if isinstance(v, dict)]
        fb_raw = _audience_rows(platforms, fb_keys)
        audience_rows = _impute_demographics(fb_raw) if fb_raw else []

    niche = niche_alignment(
        campaign.brand_industry,
        str(creator.get("primary_niche") or ""),
        list(creator.get("secondary_niches") or []),
    )
    audience = audience_demographics_score(campaign, audience_rows)
    if not raw_rows and audience_rows:
        audience = min(audience, MAX_AUDIENCE * 0.55)

    cr = campaign.content_requirements
    platform = platform_presence_score(cr.platforms, platforms)
    engagement = engagement_quality_score(cr.platforms, platforms, cr.minimum_engagement_rate)

    raw_cost = creator.get("average_campaign_cost_sar")
    try:
        cost_val = float(raw_cost) if raw_cost is not None else None
    except (TypeError, ValueError):
        cost_val = None
    br = campaign.budget_range
    budget = budget_fit_score(cost_val, br.min, br.max)

    breakdown = ScoreBreakdown(
        niche_alignment=round(niche, 2),
        audience_demographics=round(audience, 2),
        platform_presence=round(platform, 2),
        engagement_quality=round(engagement, 2),
        budget_fit=round(budget, 2),
    )
    total = round(
        breakdown.niche_alignment
        + breakdown.audience_demographics
        + breakdown.platform_presence
        + breakdown.engagement_quality
        + breakdown.budget_fit,
        2,
    )
    debug = {
        "creator_id": creator.get("creator_id"),
        "missing_required_platform_data": missing_demo,
        "required_platform_keys": req,
    }
    return breakdown, total, debug


def _three_band(score: float, cap: float, hi: float, mid: float, a: str, b: str, c: str) -> str:
    """Pick phrase a/b/c from score vs cap*hi and cap*mid (used for 4 non-niche dimensions)."""
    if score >= cap * hi:
        return a
    if score >= cap * mid:
        return b
    return c


def build_match_reason(
    campaign: CampaignMatchRequest,
    _creator: dict[str, Any],
    breakdown: ScoreBreakdown,
) -> str:
    """One sentence per dimension from the same sub-scores (_creator reserved for future use)."""
    ind = campaign.brand_industry
    if breakdown.niche_alignment >= MAX_NICHE * 0.9:
        n = f"Strong niche alignment with {ind}."
    elif breakdown.niche_alignment >= MAX_NICHE * 0.5:
        n = "Good niche overlap for the brand industry."
    elif breakdown.niche_alignment > 0:
        n = "Moderate niche relevance; consider brand safety review."
    else:
        n = "Limited niche overlap with the brand industry."

    a = _three_band(
        breakdown.audience_demographics,
        MAX_AUDIENCE,
        0.75,
        0.45,
        "Audience demographics align well with the target profile.",
        "Audience fit is reasonable on age, gender, and/or geography.",
        "Audience fit is weaker for the requested segments or regions.",
    )
    p = _three_band(
        breakdown.platform_presence,
        MAX_PLATFORM,
        0.85,
        0.45,
        "Active on required platforms with solid reach.",
        "Present on required platforms with some reach gaps.",
        "Limited presence or reach on one or more required platforms.",
    )
    e = _three_band(
        breakdown.engagement_quality,
        MAX_ENGAGEMENT,
        0.85,
        0.45,
        "Engagement rates meet or exceed the campaign threshold.",
        "Engagement is acceptable but not exceptional on all platforms.",
        "Engagement may be below the stated minimum on one or more platforms.",
    )
    u = _three_band(
        breakdown.budget_fit,
        MAX_BUDGET,
        0.95,
        0.5,
        "Typical campaign pricing fits the budget range.",
        "Pricing is close to the budget envelope.",
        "Pricing may sit outside the preferred budget range.",
    )
    return " ".join((n, a, p, e, u))
