# GridRight

AI-assisted, utility-moderated settlement platform for distributed solar energy.

See [gridright_architecture.md](./gridright_architecture.md) for the full architecture and design decisions.

## Structure

```
apps/
  web/          Next.js frontend
  api/          FastAPI backend
programs/
  gridright/    Anchor program (Solana settlement)
supabase/
  migrations/   Database migrations
```

## Quickstart

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

### Backend

```bash
cd apps/api
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Tests

```bash
# Backend
cd apps/api && pytest

# Anchor (requires Solana localnet)
cd programs/gridright && anchor test
```

## Free hosting stack (why these services)

The deployment intentionally uses services that are free **without a credit
card on file** — before reaching for a paid provider out of habit, check this
table:

| Piece | Service | Free-tier notes |
| --- | --- | --- |
| Frontend | Vercel | Root directory `apps/web`; no card needed |
| Backend | Render (web service) | 750 hrs/mo, 512MB, sleeps after 15 min idle (~30–60s cold start); suspends rather than charges on limit |
| Database/auth | Supabase Free | Auto-pauses after **7 days without a DB request** — the cron pings below prevent this |
| Scheduler / keep-alive | cron-job.org | Email-only signup; fires the jobs below |
| Weather | Open-Meteo | **Non-commercial license** — fine for a hobby deployment, revisit before handling real transactions at scale (at which point the other free tiers deserve a rethink too) |

Scheduled jobs (cron-job.org → the Render URL, `Authorization: Bearer $SCHEDULER_TOKEN`):

- `GET /health` every 10–14 min — keeps Render awake (under its 15-min sleep threshold); cheap, touches no DB.
- `POST /api/v1/forecasts/run` hourly — Phase-3 forecast + accuracy job.
- `POST /api/v1/commitments/run` once daily — Phase-5 daily Merkle commitment.

The two `/run` jobs issue real DB queries, which is also what keeps the
Supabase project from ever hitting its 7-day auto-pause.

`SCHEDULER_TOKEN` is a static secret (any long random string) accepted as an
alternative to an operator JWT on the two `/run` endpoints only — a live user
JWT would expire and silently break the cron. Treat it like any other secret;
it is never logged.

Env vars:

- **Vercel** (Production + Preview): `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` (the Render
  `.onrender.com` URL), `NEXT_PUBLIC_SOLANA_RPC`.
- **Render**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SCHEDULER_TOKEN`,
  `WEATHER_PROVIDER=open-meteo`, `CORS_ALLOWED_ORIGINS` (the Vercel production
  URL), `CORS_ALLOWED_ORIGIN_REGEX` (preview pattern, e.g.
  `https://gridright-.*\.vercel\.app`), plus Solana/badge config as needed:
  `BADGE_TREE_ADDRESS`, `COMMIT_AUTHORITY_PUBKEY`, `GROQ_API_KEY` (optional —
  recommender falls back to rules without it).

Also add the Vercel production URL to Supabase Auth's Site URL / redirect
allow-list.

## cNFT contribution badges (Phase 8)

Milestone badges are Bubblegum compressed NFTs minted on devnet when a
seller's cumulative settled kWh crosses a threshold (placeholders:
100 / 500 / 1000 kWh — see migration `20250719000004_add_badges.sql`).

One-time tree setup (funded devnet wallet at `~/.config/solana/id.json`):

```bash
cd programs/gridright
npm run badge:setup-tree   # prints the tree address
```

Current devnet badge tree: `FRAgmb48t9MgDvWgAC64wvNNgNse9m256Km1dREAF7j7`

The API's minter shells out to `scripts/mint-badge.ts` and needs:

```bash
BADGE_TREE_ADDRESS=FRAgmb48t9MgDvWgAC64wvNNgNse9m256Km1dREAF7j7
```
