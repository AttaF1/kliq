# Kliq's Creator Matching Engine

## Introduction

This small web service reads a **pool of creators** from a file, **scores every creator** against the brief request, and sends back the **best five** matches. Each match includes **sub-scores** (so user can see *why* someone ranked high) and a short **written explanation**.


---

## Submission checklist

| # | What the PDF asks for | Where to find it |
|---|------------------------|------------------|
| **1** | Short Markdown document: architecture, algorithm, key design decisions | **[ARCHITECTURE.md](./ARCHITECTURE.md)** |
| **2** | Link to a **public GitHub** repo with the full source code | *https://github.com/AttaF1/kliq* |
| **3** | **README** instructions to build and run locally with **Docker** and **Docker Compose** | **→ [Run with Docker (step by step)](#run-with-docker-and-docker-compose-step-by-step)** |
| **4** | How **matching** works, how dimensions are **weighted**, how **missing data** is handled | **→ [How matching works](#how-matching-works-plain-english)** |
| **5** | What I would improve to scale to **100k+ creators** and **sub-second** responses | **→ [Future improvements at scale](#future-improvements-at-scale)** |

---


**To use Docker (recommended for the case study):**

- [Docker](https://docs.docker.com/get-docker/) (Docker Desktop on Mac/Windows, or Docker Engine on Linux)
- **Docker Compose** — included with Docker Desktop; on Linux it is often the plugin `docker compose` (with a space)

**Optional:** [jq](https://jqlang.org/) — makes JSON pretty in the terminal. If you do not have it, run the same `curl` commands **without** `| jq`.

**To run without Docker:** Python **3.12+** on your machine.

---

## Run with Docker and Docker Compose

Follow these steps **in order** from a terminal.

### Step 1: Open the project folder

Go to the folder that contains this README, `Dockerfile`, and `docker-compose.yml`:

```bash
cd /path/to/kliq
```

*(Replace `/path/to/` with the real path on your computer.)*

### Step 2: Build the image and start the container

This downloads the base Python image (first time only), installs dependencies, copies the app, and starts the server on port **8000**:

```bash
docker compose up --build
```

- The first run can take a few minutes.
- Leave this terminal **open**. You should eventually see logs from **Uvicorn** showing the server is listening.

### Step 3: Check that the service is alive

Open a **second** terminal (keep the first one running) and run:

```bash
curl -s http://localhost:8000/health
```

You want JSON like: `{"status":"ok","creators_loaded":1000}` (the exact count depends on the dataset file).

With `jq`:

```bash
curl -s http://localhost:8000/health | jq
```

### Step 4: Try a match (sample campaign)

This sends a sample brief request and prints the top five creators:

```bash
curl -s -X POST http://localhost:8000/match \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_id": "CMP-9921",
    "brand_name": "Glow Beauty",
    "brand_industry": "Beauty & Cosmetics",
    "campaign_description": "A product launch campaign for a new skincare line targeting young women in the GCC.",
    "target_audience": {
      "age_range": [18, 34],
      "gender": "Female",
      "locations": ["Riyadh", "Jeddah", "Dubai", "Abu Dhabi"]
    },
    "content_requirements": {
      "platforms": ["Instagram", "TikTok"],
      "content_type": "Video Reel",
      "minimum_engagement_rate": 3.5
    },
    "budget_range": { "min": 5000, "max": 15000, "currency": "SAR" }
  }' | jq
```

I have added an optional feature to secure the API, to turn on API keys (see [Environment variables](#environment-variables)), add a header, for example:

`-H "X-API-Key: secret-key"`

### Step 5: Explore the interactive API page (optional)

In your browser open:

**[http://localhost:8000/docs](http://localhost:8000/docs)**

You can fill in the form for `POST /match` and click **Execute**.  
*(If text in a field has multiple lines, the service usually fixes common JSON issues; otherwise keep descriptions on one line or use `\n` inside the string.)*

### Step 6 — Stop the service

In the **first** terminal (where `docker compose up` is running), press **Ctrl+C**.

To remove the container(s) created by this compose file:

```bash
docker compose down
```

### Docker troubleshooting (quick)

| Problem | What to try |
|--------|-------------|
| **Port 8000 already in use** | Stop the other program, or change the left side in `docker-compose.yml` under `ports:` (e.g. `"8080:8000"`) and use `http://localhost:8080` in `curl`. |
| **`docker compose` not found** | Install Compose, or try the older `docker-compose` (with a hyphen) if your setup still uses it. |
| **Permission errors on Linux** | Run Docker commands with a user in the `docker` group, or use `sudo` only if your environment requires it. |

---

## Environment variables (Docker and local)

| Variable | In simple terms |
|----------|------------------|
| `CREATORS_DB_PATH` | Where the big **creators JSON file** lives. Inside Docker the default is `/app/data/creators_database.json`. |
| `LOG_LEVEL` | `INFO` (normal) or `DEBUG` (very detailed logs per creator). |
| `KLIQ_API_KEYS` | Optional. If you set one or more comma-separated keys, **`POST /match`** requires `X-API-Key` or `Authorization: Bearer`. **`GET /health`** stays open for health checks. |

In **Docker Compose**, you can uncomment and set `KLIQ_API_KEYS` in `docker-compose.yml`.

---

## Run on a Computer without Docker

1. `cd` into this project folder.  
2. Create a virtual environment: `python3 -m venv .venv`  
3. Activate it: `source .venv/bin/activate` (on Windows: `.venv\Scripts\activate`)  
4. Install packages: `pip install -r requirements.txt`  
5. Start the server: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`  
6. Open `http://localhost:8000/health` and `http://localhost:8000/docs` as above.

---

## How matching works

For **each** creator in the pool, the engine computes **five numbers** (each capped). Those numbers are added into a **total score out of 100**. Everyone is sorted by that total, the API returns the **top five**.

### How the five dimensions are weighted (caps)

The case study treats some goals as more important than others. Each dimension has a **maximum** number of points, together they add up to **100**.

| Dimension | Max points | What it measures (simply) |
|-----------|------------|---------------------------|
| **Audience** | **30** | Do the creator’s followers look like your target age, gender, and cities? |
| **Niche** | **20** | Does the creator’s topic (e.g. beauty, automotive) fit your **brand industry**? |
| **Platforms** | **20** | Are they actually on the platforms you care about, with real follower counts? |
| **Engagement** | **20** | Are their engagement rates at least near what you asked for? |
| **Budget** | **10** | Is their typical campaign cost in the ballpark of your min–max budget? |

So **audience** can move the needle the most, **budget** is still considered but capped lower.

### Rules in a bit more detail

- **Niche:** Same or synonym industries (e.g. beauty vs skincare) score highest; partial word overlap can give partial credit.  
- **Audience:** Combines age band overlap, gender mix vs your target, and whether your cities show up in their audience locations, **weighted by followers** on the platforms you requested.  
- **Platforms:** Missing a required platform hurts that part of the score.  
- **Engagement:** Compared per required platform to your **minimum**, doing better than the minimum can help.  
- **Budget:** Smooth scoring inside your range; drifting far outside reduces the budget slice.

The response also includes a **`match_reason`** string built from the same five slices so a user can see why a creator ranked well or poorly.

### Missing or incomplete creator data

Real data is messy. I made sure that service tries **not** to crash and **not** to punish creators unfairly when something is blank.

- If **audience demographics** are missing on a platform, the engine fills **neutral defaults** (e.g. mid-range age/gender, empty cities) so the math still runs 
- If a **required platform** is missing entirely, that platform contributes **zero** to platform and engagement parts, so the total score reflects the gap.  
- If **cost** is missing or invalid, budget scoring falls back to a **conservative** partial score instead of breaking the request.

---

## Logging

- **INFO:** One summary line per match request (campaign id, how many creators scored, top score).  
- **DEBUG:** Optional per creator detail, set `LOG_LEVEL=DEBUG`.  
- Core rules live in **`app/scoring.py`** without logging so automated **tests** stay simple.

---

## Tests

```bash
source .venv/bin/activate
pytest -q
```

---

## Future improvements at scale

If this engine had to serve **100,000+ creators** in **under a second** per request, the main change is: **do not score everyone every time**.

- **Shortlist first:** Use indexes or filters (niche, city, platform, budget band) to pull hundreds of candidates, not hundreds of thousands.  
- **Vectors / embeddings:** Turn briefs and profiles into vectors and use an **approximate nearest neighbor** index to find likely matches quickly, then run the detailed scorer only on that short list.  
- **Learning to rank:** Train a model on past campaign outcomes (clicks, approvals, performance) to re-rank the shortlist.  
- **Serving:** Caching for popular briefs, autoscaling, clear **latency** targets (e.g. p95), and **A/B** tests when the formula changes.  
- **Data quality:** Monitoring and alerts when follower or engagement data goes stale or looks wrong.

---

## Repository layout (short)

```
app/
  main.py        Web API: load data once, /health, /match, top 5, logs
  scoring.py     Matching rules (pure functions, easy to test)
  models.py      Request/response shapes (validated JSON)
  auth.py        Optional API key for /match
  middleware.py  Fixes common “bad JSON” from multi-line pasted text
  json_sanitize.py
data/
  creators_database.json
Dockerfile
docker-compose.yml
ARCHITECTURE.md    Deeper architecture
tests/
```

Read **[ARCHITECTURE.md](./ARCHITECTURE.md)** here
