# LMS
LMS Game

This `README.md` is designed to serve as the "Source of Truth" for your GitHub Copilot and Gemini interactions. It provides the full architectural context so that every time you open Codespaces, the AI knows exactly what you are building, the constraints of your free-tier stack, and the specific logic for your Last Man Standing model.

# Premier League LMS Predictor

A strategic decision-support system for Premier League "Last Man Standing" (LMS) competitions. This tool leverages historical market efficiency and real-time odds to optimize team selections for a 20-person pool.

## 🎯 Project Objective

To maximize survival probability in a 38-gameweek tournament by:

1. **Modeling Team Strength:** Using historical market odds from `football-data.co.uk` to build a high-convergence ELO rating system.
2. **Real-Time Calibration:** Fetching live market prices via `The Odds API` to identify the current "true" probability of victory.
3. **Path Optimization:** Calculating the "Generic Win Percentage Favored" (GWPF) to save high-value teams for future gameweeks while ensuring immediate survival.

## 🛠 Tech Stack & Constraints

* **Environment:** GitHub Codespaces (Development) + GitHub Actions (Automation).
* **Backend:** Supabase (PostgreSQL) - **Free Tier**.
* *Constraint:* 500MB Storage Limit (Optimize by only storing current season fixtures and summary ratings).
* *Constraint:* Projects pause after 7 days of inactivity (Requires a "Heartbeat" script).


* **Languages:** Python (ETL Scripts), SQL (Database), React (Minimal Frontend/Dashboard).
* **Development Style:** AI-Assisted "Vibe Coding" for Product Managers.

## 📊 Data Pipeline (ETL)

| Source | Frequency | Purpose |
| --- | --- | --- |
| **football-data.co.uk** | One-time / Seasonal | Historical CSV odds and results to initialize and calibrate ELO ratings. |
| **FPL API** | Weekly | Reliable source for gameweek boundaries, deadlines, and match status (postponements). |
| **The Odds API** | Every 6 hours | Live 1X2 market odds (soccer_epl) for current-week win probabilities. |

## 🧠 Modeling Logic

### 1. ELO-Odds System

Instead of simple win/loss results, we use an **ELO-Odds** model ($K=175$) where team ratings are updated based on the delta between their expected win probability (from market odds) and the actual result. This allows for faster convergence to "true" skill levels.

* **Home Advantage:** +75 to +100 ELO points.
* **De-vigging:** The **Power Method** is used to remove bookmaker margins from raw odds to find the fair probability.

### 2. Selection Strategy

The model ranks available teams for the current gameweek based on a **Selection Score**:


$$Score_{team} = P(W_{team, t}) - \lambda \cdot Utility(future)$$


This ensures we don't "burn" Manchester City in a week where a lower-tier team has a high (but slightly lower) probability of winning, preserving the big teams for harder weeks later in the season.

## 🗄 Database Schema (Supabase)

* `teams`: `id`, `name`, `current_elo`, `is_active`.
* `fixtures`: `id`, `gameweek`, `home_team_id`, `away_team_id`, `kickoff`, `status`.
* `odds`: `fixture_id`, `bookmaker`, `raw_h`, `raw_d`, `raw_a`, `de_vigged_win_prob`.
* `user_selections`: `user_id`, `gameweek`, `team_id`, `result`.

## 🔌 Connect This Repo To Supabase Dashboard

The repo is now prepared with:

* `.env.example` for your Supabase project values.
* `.gitignore` that ignores `.env` secrets.
* `supabase/config.toml` for Supabase CLI project config.
* `supabase/migrations/202603160001_init_schema.sql` for the baseline LMS tables.

### 1) Create your local `.env`

```bash
cp .env.example .env
```

Open `.env` and fill values from **Supabase Dashboard -> Project Settings -> API**.

### 2) Authenticate Supabase CLI

```bash
npx --yes supabase login
```

### 3) Link this repo to your hosted Supabase project

From the dashboard URL (`https://supabase.com/dashboard/project/<project-ref>`), copy `<project-ref>` and run:

```bash
npx --yes supabase link --project-ref <project-ref>
```

### 4) Create your first tables in Supabase

```bash
npx --yes supabase db push
```

This applies `supabase/migrations/202603160001_init_schema.sql` to your hosted database.

### 5) If `.env` was previously committed to git

```bash
git rm --cached .env
git commit -m "Stop tracking .env"
```

Your `.env` file stays local, and `.env.example` remains the safe file to commit.

## 🤖 AI Interaction Guidelines (For Copilot/Gemini)

* **PM Persona:** I am a Product Manager. Provide code in small, testable chunks.
* **Context:** Always assume we are operating within Supabase Free Tier limits.
* **Safety:** Prioritize Row Level Security (RLS) for all user-facing data.
* **Automation:** All heavy lifting (ELO updates, data fetching) must be written as Python scripts to be executed via GitHub Actions.

## 💓 Maintenance

* **Heartbeat Script:** `scripts/heartbeat.py` runs every 3 days via GitHub Actions to keep the Supabase project active.
* **Backups:** Historical CSVs should be processed and discarded; only store the final ELO ratings in the `teams` table to save space.

---

*Created by - Product Manager | Last Updated: March 2026*