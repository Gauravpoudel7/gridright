# GridRight — Hackathon Demo Presentation

> **Format:** 12 slides · 3 minutes · Clean light theme
> **Pitch style:** Simple, term-rich, visual-first

---

## Slide 1 — Title

**GridRight**
*P2P community solar trading. AI-powered dispatch. Solana settlement. cNFT badges.*

Live demo → gridright.netlify.app

---

## Slide 2 — The Problem

**Your solar panels sit idle half the day.**

- A **prosumer** (household that both produces and consumes) generates more than they can use at noon
- That extra energy goes to waste
- Net metering pays pennies — not real value
- Your neighbor is buying grid power at full retail price

**Result:** Sun is free. Power is not. The gap is lost money for everyone.

---

## Slide 3 — The Hidden Problem

**There is no easy way to share solar between neighbors.**

- Feed-in tariffs pay a fraction of retail price
- Sending surplus to a specific neighbor? Almost impossible
- Communities want to pool their DERs (Distributed Energy Resources) — but the tools don't exist
- **50% of the world can't even put panels on their roof** — renters, apartments, shaded homes. Locked out of the solar revolution.

---

## Slide 4 — Our Solution

**GridRight is a community energy pool.**

- **Prosumers / Sellers** — contribute surplus kWh to a shared pool
- **Buyers** — draw from the pool at a fair community price
- **Operator** — balances the flow, approves dispatches, handles disputes

**One neighborhood. One pool. Fair price. Real savings.**

---

## Slide 5 — How It Works (NEW)

**From rooftop to reward in four steps.**

Flow diagram (left to right):

☀️ Prosumer contributes
→ 🌊 Community Pool (aggregates DER supply & demand)
→ 🤖 AI Engine recommends pool dispatch
→ 👤 Operator approves (HITL)
→ ⛓️ Solana settles P2P trade (Anchor program)
→ 🏅 cNFT badge minted (Metaplex Bubblegum)

Key terms introduced: **P2P Energy Trading · Pool Dispatch · HITL · cNFT**

---

## Slide 6 — AI + Human in the Loop (NEW)

**AI recommends. Operator decides.**

Left column — AI Engine:
- Ingests real-time pool state, supply, demand, price signals
- Runs time-series forecasts on solar production curves
- Ranks pool dispatch options by cost and balance
- Flags anomalies to the exception queue

Right column — Operator:
- Reviews AI recommendations — never a done deal
- Manages exception queue: disputes, anomalies, out-of-band trades
- Approves or rejects each dispatch
- Sets pool policy: price floor, max draw per household

**Callout: "Trust is the moat. Autonomous AI settlement is how you make the front page for the wrong reason."**

---

## Slide 7 — What We Built

**Three things, working together:**

A. **Pool App** (Next.js + Supabase RLS) — dashboard for neighbors to sign up, track kWh contribution, see savings

B. **Smart Engine** (Python FastAPI + AI) — recommends pool dispatch; exception queue for operator review; HITL design

C. **Settlement Layer** (Anchor + Bubblegum) — every P2P trade on Solana; cNFT milestone badges at 100 kWh contribution

---

## Slide 8 — How We Built It

| Layer | Technology | Key detail |
|---|---|---|
| Web app | Next.js | SSR + Netlify |
| Backend | Python / FastAPI | AI forecasting + pool logic |
| Database & auth | Supabase (Postgres) | RLS per-user isolation |
| Blockchain | Solana / Anchor | Custom IDL, every trade on-chain |
| cNFT badges | Metaplex Bubblegum | Compressed NFTs, cheap to mint |
| Scheduler | cron-job.org | Hourly forecasts, daily settlements |
| Hosting | Netlify · Render · Supabase | 100% free tier |

*Fully deployed. No credit card. No mocks. Real users could sign up today.*

---

## Slide 9 — The Market

**Community solar is exploding.**

- US market: **$3.2 billion in 2025**, growing 19% YoY
- Already serving **1.3 million US households**
- EPA goal: **5 million homes by 2030** (Solar for All)
- Global VPP market: **$7B → $24B by 2030**

> **Virtual Power Plant (VPP)** — a coordinated network of DERs acting as one power source. GridRight is the community-scale VPP layer that doesn't yet exist.

**Anyone with a roof — or without one — is a potential user.**

---

## Slide 10 — Where This Works Today

**18 countries already pay you for surplus solar.**

| Country | Program |
|---|---|
| 🇺🇸 USA | Net metering (state-by-state) |
| 🇦🇺 Australia | Feed-in tariff |
| 🇩🇪 Germany | EEG feed-in tariff |
| 🇯🇵 Japan | FIT surplus purchase |
| 🇬🇧 UK | Smart Export Guarantee |
| 🇮🇹 Italy | Scambio Sul Posto |
| 🇪🇸 Spain | Surplus compensation |
| 🇫🇷 France | Autoconsommation sale |
| 🇧🇪 Belgium | Flanders net metering |
| 🇩🇰 Denmark | Net metering up to 6 kW |
| 🇨🇦 Canada | Ontario, Alberta, BC |
| 🇮🇳 India | Rooftop net metering |
| 🇧🇷 Brazil | REN 482/2012 |
| 🇲🇽 Mexico | Residential net metering |
| 🇿🇦 South Africa | Feed-in tariff |
| 🇮🇱 Israel | Net metering |
| 🇳🇱 Netherlands | Saldering net metering |
| 🇰🇷 South Korea | RPS surplus purchase |

**GridRight adds the sharing layer on top of programs that already exist.**

---

## Slide 11 — Future & Business Model

**Next steps:**
- Pilot in 1–2 US community solar programs (Minnesota, NY)
- Add battery storage + EV charging to the pool (expand DER types)
- White-label the platform for utility companies and energy co-ops
- VPP interoperability via OpenADR standard

**How we make money:**
- 1–2% fee on every pool trade
- SaaS subscription for utility/co-op operators
- Premium AI forecasting for grid operators
- cNFT badge marketplace

---

## Slide 12 — Why This Wins

✅ **Rare** — community-level P2P solar trading with real on-chain settlement
✅ **Proven market** — 18 countries paying for surplus solar; we add the sharing layer
✅ **Live today** — not a slide deck, a running app → gridright.netlify.app
✅ **Inclusive** — works for renters and apartments, not just homeowners
✅ **Open by design** — HITL architecture; AI recommends, humans decide; trust is the moat
✅ **First-mover** — community solar + Solana settlement + cNFT badges in one deployed product

**Thank you.**
gauravpoudel.com · gridright.netlify.app · github.com/Gauravpoudel7/gridright

---

### Key Terms Reference

| Term | Definition |
|---|---|
| Prosumer | Household that both produces and consumes energy |
| DER | Distributed Energy Resource — rooftop, battery, EV |
| Pool Dispatch | AI-ranked matching of supply to demand in the pool |
| HITL | Human-in-the-Loop — AI recommends, human decides |
| Net Metering | Grid credit for surplus solar exported |
| Feed-in Tariff (FIT) | Fixed payment for energy exported to the grid |
| VPP | Virtual Power Plant — coordinated network of DERs |
| P2P Energy Trading | Peer-to-peer direct energy exchange |
| cNFT | Compressed NFT — on-chain badge via Metaplex Bubblegum |
| Anchor | Solana smart contract framework |
| RLS | Row-Level Security — per-user data isolation in Supabase |
| kWh | Kilowatt-hour — unit of energy traded in the pool |
| OpenADR | Open standard for automated demand response |
