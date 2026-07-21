# Phantom Wallet — Manual QA Checklist

Run in a real browser with the Phantom extension installed. Use two browser
profiles (or two browsers) if you want to test seller and operator flows
side by side. Backend, web app, and local Supabase must be running; the
operator wallet needs devnet SOL (`solana airdrop 2 <address> --url devnet`).

Expected program: `88HxyoRrb9NzqWfk34SCoqHZcMFxmmHg6XVNpcVPxoFL` (devnet).

## 1. Wallet on wrong network (mainnet instead of devnet)

- [ ] In Phantom → Settings → Developer settings, make sure **Testnet mode is OFF** (i.e. Phantom is on mainnet).
- [ ] Sign in as operator, connect the wallet, and attempt "Pay seller" on a settled contribution.
- [ ] **Expected:** the transaction fails — the app's RPC connection is hardcoded to devnet, so the simulation/send should error (program doesn't exist on the mainnet fork Phantom simulates against, or Phantom warns about network mismatch). The contribution row must NOT flip to settled; the button should show "Failed — retry".
- [ ] Switch Phantom to Testnet mode → Devnet and retry. **Expected:** transaction succeeds.

## 2. User rejects the connection popup

- [ ] Signed in (either role), click the wallet connect button, and click **Cancel/Reject** in the Phantom popup.
- [ ] **Expected:** the app stays in disconnected state — no pubkey shown, no crash, no console error loop. `profiles.wallet_address` is NOT written (check the dashboard's "Saved:" line stays absent, or query the profiles table).
- [ ] Click connect again. **Expected:** the popup reappears normally (no stuck state).

## 3. User rejects the transaction signing popup

- [ ] As operator with a connected wallet, click "Pay seller", then click **Reject** in the Phantom signing popup.
- [ ] **Expected:** button returns to a retriable state showing "Failed — retry" with an error message (user rejection); `contributions.tx_signature` stays empty and status does NOT change to pending/settled.
- [ ] Click "Pay seller" again and approve. **Expected:** normal payout flow completes (pending → confirmed), proving the rejected attempt left no bad state.

## 4. Insufficient SOL balance for the payout

- [ ] Use an operator wallet whose devnet balance is below the payout amount (create a fresh Phantom account, or pick a contribution whose payout converts to more lamports than the wallet holds — at the placeholder rate, payout_cents / 15,000 SOL).
- [ ] Click "Pay seller" and approve in Phantom.
- [ ] **Expected:** transaction fails at simulation or on-chain with an insufficient-funds error; the UI shows failed state, and the contribution row does NOT flip to settled. No partial transfer occurs (check seller wallet balance unchanged on https://explorer.solana.com/?cluster=devnet).

## 5. Disconnect mid-flow (after connecting, before signing)

- [ ] As operator, connect the wallet and confirm the "Pay seller" button is enabled.
- [ ] Disconnect from **inside Phantom** (extension → connected sites → disconnect), NOT via the app button, so the app has to notice externally.
- [ ] Click "Pay seller".
- [ ] **Expected:** no transaction popup appears with a stale key; the action fails gracefully ("Operator wallet not connected" or the wallet modal reopens). No pending write to the contributions row.
- [ ] Reconnect and retry. **Expected:** payout completes normally.

## After the run

- [ ] Every failure case above left `contributions.status` unchanged (verify in Supabase Studio: http://127.0.0.1:54323).
- [ ] Every success case produced a `tx_signature` that resolves on the devnet explorer.
