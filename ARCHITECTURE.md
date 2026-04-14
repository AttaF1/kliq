# Architecture

## Why this architecture

I chose a **small, boring, and explicit** shape on purpose:

1. **FastAPI + Pydantic (`main.py`, `models.py`)**,  The requirements in the PDF defines a JSON contract, Pydantic validates requests and responses automatically and generates OpenAPI at `/docs`. That keeps the HTTP layer thin and errors visible early.

2. **Pure rule engine (`scoring.py`)** — All matching math lives in **one module** with **no I/O and no logging**. That separation means: (a) the same functions are easy to unit test, (b) behavior is deterministic and auditable for stakeholders, and (c) `main.py` only handles transport, file load, sorting, and operational logs. For a case-study pool (~1k creators), a transparent **weighted rule-based** scorer is appropriate; it matches the brief’s explainability requirement without needing training data or a model-serving stack.

3. **Load creators once at startup** — The dataset is a static JSON file. Reading it in the FastAPI **lifespan** hook avoids re-parsing the file on every request and keeps latency predictable for the expected scale.

4. **Docker / Compose** — One command reproduces the same runtime everywhere (Python version, dependencies, default paths). That supports reviewers and hiring managers who only want to run the container.

5. **Optional hardening without changing the contract** — `auth.py` (API keys) and `middleware.py` / `json_sanitize.py` (common JSON paste issues) sit **outside** the scoring core so the PDF’s `POST /match` shape and scoring semantics stay the story; security and UX fixes are add-ons.

**Trade-off:** This is **not** yet a distributed or ML-heavy system. The closing section **Beyond the case study** (and **README → “Future improvements at scale”**) describe how we would evolve it for 100k+ creators and stricter latency.

---

## Matching logic, scoring weights, and incomplete data

### How matching works (concise)

For each `POST /match` request:

1. The brief is validated into a **`CampaignMatchRequest`**.
2. Every creator in the in-memory list is scored with **`score_creator()`**.
3. Five sub-scores are computed (each **capped**), summed to a **total out of ~100**, rounded.
4. Creators are **sorted by total descending**; the API returns the **top 5** with **`score_breakdown`** and a human-readable **`match_reason`** (`build_match_reason()`), built from the same numbers so text and math stay aligned.

Per dimension (still at a high level):

| Dimension | Role in the engine |
|-----------|-------------------|
| **Niche** | Brand industry vs creator `primary_niche` / `secondary_niches`: synonym **equivalence groups** (normalized labels), then **token overlap** (Jaccard) for partial credit; secondary niche matches at **85%** of the primary cap. |
| **Audience** | Target age vs creator’s **18–34** share, gender vs **female %**, cities vs **top_locations**, aggregated **follower-weighted** across the **required** platforms’ rows. |
| **Platform presence** | Required platforms from the brief must exist under `platforms` with meaningful followers; the platform cap is **split across** required platforms. |
| **Engagement** | Per required platform, engagement vs the brief’s **minimum**; rewards being above the bar. |
| **Budget** | Creator `average_campaign_cost_sar` vs brief min/max with **smooth decay** outside the band. |

### How the dimensions are weighted

The brief treats some goals as **more important** than others. We express that with **hard caps** (maximum points per dimension), not with hidden multipliers after the fact. Constants in `scoring.py`: **`MAX_AUDIENCE = 30`**, **`MAX_NICHE = 20`**, **`MAX_PLATFORM = 20`**, **`MAX_ENGAGEMENT = 20`**, **`MAX_BUDGET = 10`** — **total 100**. Audience can move the total the most; budget still matters but cannot dominate the decision. Each scorer returns a value in **`[0, cap]`**; the **overall match score** is their sum.

### Missing or incomplete creator data

| Situation | Handling |
|-----------|----------|
| Missing **`audience_demographics`** on a platform | **Impute** neutral defaults (e.g. **55%** 18–34, **50%** female, empty locations) so scores stay defined and creators are not arbitrarily zeroed. |
| Demographics only from **non-required** platforms | Audience score is **capped** (weaker signal — see `score_creator()`), so proxy platforms do not fully substitute for missing required-platform data. |
| Required **platform** missing or empty | That platform contributes **0** to the platform and engagement parts of the score. |
| Invalid / missing **cost** | Budget uses conservative handling so the pipeline does not fail; the budget dimension reflects uncertainty. |

This keeps the API **robust** and the breakdown **interpretable** when the underlying social data is patchy — which matches real influencer datasets.

---

## PDF → code

| Requirement | Implementation |
|-------------|----------------|
| `POST /match` | `app/main.py` + `CampaignMatchRequest` in `app/models.py` |
| Score all creators in pool | Loop + `total_creators_evaluated` |
| Five weighted dimensions | Point caps **30 / 20 / 20 / 20 / 10** in `app/scoring.py` |
| Top **5** matches | Sort by `match_score`, `[:5]` |
| `score_breakdown` + `match_reason` | `ScoreBreakdown` + `build_match_reason()` |
| Logging | `INFO` + optional `DEBUG` in `app/main.py` |
| Docker | `Dockerfile`, `docker-compose.yml` |

## Layout

```
app/main.py     — FastAPI, load JSON, /match loop, sort, logging
app/models.py   — Pydantic request/response (PDF JSON contract)
app/scoring.py  — Pure scoring: caps, rules, imputation, explanations (no I/O)
app/auth.py     — Optional API keys for POST /match
app/middleware.py + json_sanitize.py — ASGI body normalization for common JSON client mistakes
```

`scoring.py` is **pure** (deterministic, no logging) so tests stay fast and `main.py` stays thin.

## `app/scoring.py` (streamlined)

The module is organized around **one orchestrator** and small helpers:

| Piece | Role |
|-------|------|
| **Constants** | `MAX_*`, `NICHE_EQUIVALENCE_GROUPS`, `PLATFORM_KEY_MAP` |
| **Niche** | `niche_alignment()` + `_norm_label`, `_tokens`, `_jaccard`, `_same_niche_group`, `_niche_points_from_jaccard` |
| **Audience** | `audience_demographics_score()` + `_age_overlap_18_34`, `_location_hit_ratio`, `_avg_by_followers` |
| **Platforms** | `_brief_platform_keys(..., mapped_only=…)` — one helper for both “all keys” and “IG/TT/YT only” |
| **Iterate platforms** | `_platform_payloads()` — shared by platform presence + engagement (no duplicate `isinstance` loops) |
| **Presence / engagement** | `platform_presence_score()`, `engagement_quality_score()` |
| **Budget** | `budget_fit_score()` |
| **Audience prep** | `_audience_rows()`, `_impute_demographics()` |
| **Orchestration** | `score_creator()` — platforms → audience rows → five scores → round → `debug` dict |
| **Copy** | `build_match_reason()` — niche uses explicit bands; other four use `_three_band()` to avoid repeated if/elif |

**Optimizations (same math as before):** merged duplicate “brief platform name → JSON key” logic; shared platform dict iteration; compact `build_match_reason` for four dimensions; shorter module docstring (details live here + README).

## Request flow

```mermaid
flowchart LR
  Client -->|POST /match| API[FastAPI]
  API --> Val[Pydantic]
  Val --> Loop[Each creator]
  Loop --> Score[score_creator]
  Score --> Sort[Sort by match_score]
  Sort --> Top5[Top 5]
```

## Logging

- **INFO** (`main.py`): campaign id, count evaluated, top score.
- **DEBUG** (`main.py`): per-creator breakdown + `debug` from `score_creator` (`LOG_LEVEL=DEBUG`).

## Container

Python 3.12 slim; `CREATORS_DB_PATH` overrides dataset path.

## Beyond the case study

See **README → “Future improvements at scale”** (shortlist/indexes, ANN, feature store, etc.).
