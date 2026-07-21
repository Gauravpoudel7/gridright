"use server";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type MeterRegisterResult = {
  ok: boolean;
  meterDeviceId?: string;
  deviceToken?: string;
  error?: string;
};

/** Register (or replace) the caller's smart meter via the API. The plaintext
 * device token is returned exactly once — the API stores only its hash. */
export async function registerMeterDevice(meterDeviceId: string): Promise<MeterRegisterResult> {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not authenticated" };

  const res = await fetch(`${API_BASE}/api/v1/sellers/me/meter-device`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ meter_device_id: meterDeviceId }),
    cache: "no-store",
  });
  if (!res.ok) return { ok: false, error: `Registration failed (${res.status})` };
  const data = await res.json();
  return { ok: true, meterDeviceId: data.meter_device_id, deviceToken: data.device_token };
}
