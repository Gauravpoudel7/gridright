# GridRight virtual meter simulator

A standalone Python script that pushes small dummy solar readings to the
GridRight API. No dependencies beyond the standard library.

## Quick start

### 1. Apply for a seller account

Go to `https://gridright.netlify.app/apply` and submit an application.
Use any email you control. Wait for the operator to approve it — you'll
receive a temp password by email.

### 2. Sign in and bind the meter

1. Sign in at `/login` with the credentials from the email.
2. Change your password when prompted.
3. In the **Meter binding** section enter pairing code: `VSIM-001`
   (or any code that doesn't start with `EXPIRED`, `CLAIMED`, or `BADCODE`).
4. Click **Bind meter** — the dashboard shows a **one-time device token**.
   Copy it immediately; it is never shown again.

### 3. Run the simulator

```bash
python sim.py --token gr_meter_<your_token> --meter-id METER-VSIM-001
```

Or with env vars:

```bash
export GRIDRIGHT_DEVICE_TOKEN=gr_meter_<your_token>
export GRIDRIGHT_METER_ID=METER-VSIM-001
python sim.py
```

Readings are pushed every 60 seconds by default. The **Smart meter** section
of the seller dashboard updates in real time via Supabase Realtime.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--token` | `$GRIDRIGHT_DEVICE_TOKEN` | Device token from the binding step |
| `--meter-id` | `METER-VSIM-001` | Meter ID shown in the dashboard |
| `--api` | `https://gridright-api.onrender.com` | API base URL |
| `--interval` | `60` | Seconds between readings |
| `--once` | off | Push one reading and exit |

## Dummy data model

The sim generates a realistic day/night solar curve:

- **Generation**: peaks around noon, zero at night (~0.05–0.35 kWh/reading)
- **Consumption**: small constant base load (~0.05–0.07 kWh/reading)
- **Grid export**: surplus after self-use (generation − consumption × 0.7–0.95)

These values are intentionally small so the operator's devnet SOL balance
lasts through many settlement cycles. A full day of readings totals roughly
2–5 kWh of grid export.

## Pairing codes (simulated service)

When `METER_SERVICE_URL` is not set on the API, the simulated pairing client
is used. Code outcomes are encoded in the prefix:

| Code prefix | Outcome |
|-------------|---------|
| `VSIM-001` (or any normal code) | Success — meter ID becomes `METER-<CODE>` |
| `EXPIRED-...` | Expired code error |
| `CLAIMED-...` | Already claimed by another account |
| `BADCODE` | Invalid code |
