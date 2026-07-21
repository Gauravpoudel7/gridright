// Fleet outlook section (Phase 4): fleet-wide expected surplus vs demand,
// confidence band, per-seller breakdown, accuracy-drift flags, NL summary.
// Pure presentational — data is fetched server-side by the dashboard page.

type HourlyOutlook = {
  forecast_for: string;
  predicted_surplus_kwh: number;
  lower_kwh: number;
  upper_kwh: number;
  expected_demand_kwh: number;
  net_position_kwh: number;
};

type SellerOutlook = {
  seller_id: string;
  total_predicted_kwh: number;
  mean_confidence: number;
};

type DriftFlag = {
  seller_id: string;
  mean_abs_delta_kwh: number;
  scored_count: number;
};

export type FleetOutlookData = {
  horizon_hours: number;
  total_predicted_surplus_kwh: number;
  total_expected_demand_kwh: number;
  net_position_kwh: number;
  summary: string;
  hourly: HourlyOutlook[];
  per_seller: SellerOutlook[];
  drift_flags: DriftFlag[];
};

export const EMPTY_FLEET: FleetOutlookData = {
  horizon_hours: 24,
  total_predicted_surplus_kwh: 0,
  total_expected_demand_kwh: 0,
  net_position_kwh: 0,
  summary: "",
  hourly: [],
  per_seller: [],
  drift_flags: [],
};

function fmt(v: number, d = 1) { return v.toFixed(d); }

/** Confidence band chart: supply band (low–high) + demand line, inline SVG. */
function BandChart({ hourly }: { hourly: HourlyOutlook[] }) {
  if (hourly.length < 2) return null;
  const width = 640;
  const height = 80;
  const max = Math.max(0.1, ...hourly.map((h) => Math.max(h.upper_kwh, h.expected_demand_kwh)));
  const x = (i: number) => (i / (hourly.length - 1)) * width;
  const y = (v: number) => height - (v / max) * (height - 6) - 3;
  const line = (pick: (h: HourlyOutlook) => number) =>
    hourly.map((h, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(pick(h)).toFixed(1)}`).join(" ");
  // Band polygon: upper edge forward, lower edge back.
  const band =
    hourly.map((h, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(h.upper_kwh).toFixed(1)}`).join(" ") +
    " " +
    [...hourly].reverse().map((h, i) => `L${x(hourly.length - 1 - i).toFixed(1)},${y(h.lower_kwh).toFixed(1)}`).join(" ") +
    " Z";

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-20 w-full" role="img" aria-label="Fleet supply forecast band vs expected demand">
      <path d={band} className="fill-green-500/15" />
      <path d={line((h) => h.predicted_surplus_kwh)} fill="none" className="stroke-green-500" strokeWidth="1.5" />
      <path d={line((h) => h.expected_demand_kwh)} fill="none" className="stroke-orange-400" strokeWidth="1.5" strokeDasharray="4 3" />
    </svg>
  );
}

export function FleetOutlook({ data }: { data: FleetOutlookData }) {
  const hasData = data.hourly.length > 0;
  const net = data.net_position_kwh;

  return (
    <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        Fleet outlook — next {data.horizon_hours}h
      </h2>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Aggregated seller forecasts vs expected community demand.
      </p>

      {!hasData ? (
        <p className="text-sm text-zinc-500">
          No forecasts yet — run the forecast job once sellers have meter history.
        </p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">Expected surplus</p>
              <p className="text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
                {fmt(data.total_predicted_surplus_kwh)}<span className="ml-1 text-sm font-normal text-zinc-500">kWh</span>
              </p>
            </div>
            <div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">Expected demand</p>
              <p className="text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
                {fmt(data.total_expected_demand_kwh)}<span className="ml-1 text-sm font-normal text-zinc-500">kWh</span>
              </p>
            </div>
            <div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">Net position</p>
              <p className={`text-2xl font-semibold tabular-nums ${net >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                {net >= 0 ? "+" : ""}{fmt(net)}<span className="ml-1 text-sm font-normal text-zinc-500">kWh</span>
              </p>
              <p className="text-xs text-zinc-500">{net >= 0 ? "surplus" : "shortfall"}</p>
            </div>
          </div>

          <BandChart hourly={data.hourly} />
          <p className="mb-4 mt-1 text-xs text-zinc-500">
            <span className="mr-3 inline-flex items-center gap-1"><span className="inline-block h-1.5 w-3 rounded bg-green-500" /> supply (band = confidence)</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-1.5 w-3 rounded bg-orange-400" /> demand</span>
          </p>

          {data.summary && (
            <p className="mb-4 rounded border border-zinc-200 bg-zinc-50 p-3 text-sm text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
              {data.summary}
            </p>
          )}

          {/* Per-seller breakdown */}
          <table className="mb-2 w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
                <th className="pb-2 pr-4 font-medium">Seller</th>
                <th className="pb-2 pr-4 font-medium">Predicted kWh</th>
                <th className="pb-2 pr-4 font-medium">Confidence</th>
                <th className="pb-2 font-medium">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {data.per_seller.map((s) => {
                const drift = data.drift_flags.find((d) => d.seller_id === s.seller_id);
                return (
                  <tr key={s.seller_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/50">
                    <td className="py-2 pr-4 font-mono text-xs">{s.seller_id}</td>
                    <td className="py-2 pr-4 tabular-nums">{fmt(s.total_predicted_kwh)}</td>
                    <td className="py-2 pr-4 tabular-nums">{Math.round(s.mean_confidence * 100)}%</td>
                    <td className="py-2">
                      {drift ? (
                        <span className="inline-block rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
                          drifted ±{fmt(drift.mean_abs_delta_kwh)} kWh ({drift.scored_count} scored)
                        </span>
                      ) : (
                        <span className="text-xs text-zinc-500">ok</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
