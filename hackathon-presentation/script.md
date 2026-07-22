# GridRight — Pitch Script (3 minutes)

> Read this naturally, pause where marked. Slides appear behind you.
> Total target: ~420 words ≈ 3:00 minutes at natural pace.
> Tip: advance slides on the bold cues below.

---

## [0:00] SLIDE 1 — Hook
*[Calm, confident, eye contact with audience]*

"Your neighbor has solar. You're paying full price for power. What if you could share it — fairly, instantly, with on-chain proof? This is GridRight: a community energy pool where neighbors trade the sun they catch. P2P solar. Real settlement. Real savings."

---

## [0:13] SLIDE 2 — Problem
*[Set the scene, slow and clear]*

"Here's the thing about solar. A household that both produces and consumes its own energy is called a **prosumer**. At noon, a typical prosumer's rooftop is generating far more than their home can use. That surplus? It just disappears. Meanwhile, the neighbor down the street is buying power from the grid at full retail price. Most countries have something called net metering — where you get a tiny credit for sending energy back. But it pays pennies. Sun is free. Power is not. The gap between them is lost money for everyone."

---

## [0:38] SLIDE 3 — Hidden Problem
*[The bigger insight — emotional peak here]*

"And the problem goes deeper. There's no easy way to send your surplus solar to a specific neighbor. Communities want to pool their distributed energy resources — DERs — their rooftops, batteries, EVs — but the tools simply don't exist. And here's the real gut punch: fifty percent of people can't even put panels on their own roof. Renters, apartments, shaded homes. They are locked out of the solar revolution entirely."

---

## [1:02] SLIDE 4 — Solution
*[The turn — brighter tone, smile]*

"GridRight fixes this. We built a community energy pool. Households with solar — the prosumers — contribute their surplus kilowatt-hours to a shared pool. Households without solar draw from the pool at a fair price. A community operator balances the flow. One neighborhood, one pool, fair price, real savings."

---

## [1:17] SLIDE 5 — How It Works
*[Walk the flow left to right, gesture across slide]*

"Here's the end-to-end loop. A prosumer's surplus hits the pool. Our AI engine reads the pool state, runs a forecast on production curves, and ranks the best pool dispatch options — who exports, who imports, and at what rate. That recommendation goes to the operator, who reviews it and approves. Once approved, our custom Solana program records the trade on-chain. And the prosumer earns a compressed NFT badge — a cNFT minted via the Metaplex Bubblegum protocol."

---

## [1:38] SLIDE 6 — AI + Human in the Loop
*[Confident, principled]*

"The architecture is intentional. The AI never finalizes a trade. It recommends — and a human operator always decides. Out-of-band situations go to an exception queue for manual review. This human-in-the-loop design, HITL, is not a limitation — it is the trust moat. Autonomous AI settlement is how you end up on the front page for the wrong reason."

---

## [1:55] SLIDE 7 — What We Built
*[Show the work, steady pace]*

"Three things working together. A pool app built on Next.js, secured with Supabase row-level security so every user sees only their own data. A smart engine — Python FastAPI, AI forecasting, exception queue. And a settlement layer: a custom Anchor program on Solana for every P2P trade, with cNFT badges at contribution milestones."

---

## [2:08] SLIDE 8 — Tech Stack
*[Quick, humble, glide through]*

"The stack is deliberately boring — Next.js, FastAPI, Supabase, Anchor. We added Metaplex Bubblegum for compressed NFTs, and cron-job.org to run hourly forecasts and keep the API awake. Fully deployed on the free tier: Netlify, Render, hosted Supabase. No credit card. No mocks. Real users can sign up today."

---

## [2:18] SLIDE 9 — Market
*[Show the size, energy in voice]*

"And the market is huge. US community solar is a three-point-two-billion-dollar market growing nineteen percent a year, already serving one-point-three million homes. The EPA wants five million homes on community solar by 2030. The global virtual power plant market — VPP, networks of DERs acting as one coordinated source — is on track to triple to twenty-four billion dollars. Anyone with a roof, or without one, is a potential user."

---

## [2:32] SLIDE 10 — Countries
*[Credibility, glide through]*

"And this isn't a future bet. Eighteen countries already pay people for surplus solar — net metering, feed-in tariffs, export guarantees. The US, Australia, Germany, Japan, the UK, India, and more. GridRight adds the sharing layer on top of programs that already exist."

---

## [2:40] SLIDES 11 & 12 — Future + Close
*[Close strong, eye contact]*

"Next: we pilot with a US community solar program, add batteries and EVs to the pool, and white-label for utilities. VPP interoperability via the OpenADR standard is on the roadmap. We make money through a small transaction fee, operator subscriptions, and premium AI forecasting. Small fees, large volume, real network effects. Why does this win? It's rare — no one is doing community P2P solar with real on-chain settlement. It's proven — the markets exist. It's live today. And it's inclusive — renters can join too. Thank you."

---

### Timing summary
| Section | Time |
|---|---|
| Hook | 0:00 – 0:13 |
| Problem | 0:13 – 0:38 |
| Hidden Problem | 0:38 – 1:02 |
| Solution | 1:02 – 1:17 |
| How It Works | 1:17 – 1:38 |
| AI + HITL | 1:38 – 1:55 |
| What We Built | 1:55 – 2:08 |
| Tech Stack | 2:08 – 2:18 |
| Market | 2:18 – 2:32 |
| Countries | 2:32 – 2:40 |
| Future + Close | 2:40 – 3:00 |

### Delivery tips
- **Slow down on slide 3** — "locked out of the solar revolution" is the emotional peak
- **Smile at slide 4** — the turn to the solution
- **Gesture across slide 5** — walk the flow diagram left to right
- **Lean in on slide 6** — the HITL principle is the trust argument; make it land
- **Glide through slide 10** — don't list countries, just gesture at the table
- **Eye contact on slide 12** — close to camera, not to slide

### Key terms to use naturally in delivery
| Term | Meaning |
|---|---|
| Prosumer | Household that both produces and consumes energy |
| DER | Distributed Energy Resource — rooftop, battery, EV |
| Pool dispatch | AI-ranked matching of supply to demand in the pool |
| HITL | Human-in-the-Loop — AI recommends, human decides |
| Net metering | Grid credit program for surplus solar |
| Feed-in tariff (FIT) | Fixed payment for energy exported to the grid |
| VPP | Virtual Power Plant — coordinated network of DERs |
| P2P Energy Trading | Peer-to-peer direct energy exchange between households |
| cNFT | Compressed NFT — cheap on-chain badge via Bubblegum |
| Anchor | Solana smart contract framework (like Hardhat for EVM) |
| RLS | Row-Level Security — Supabase data isolation per user |
| kWh | Kilowatt-hour — the unit of energy traded in the pool |
