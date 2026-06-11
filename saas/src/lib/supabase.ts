import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anon) {
  // Surfaced loudly in the console; the UI also shows a config banner.
  console.error("Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY in saas/.env");
}

export const supabase = createClient(url, anon, {
  auth: { persistSession: true },
});

export const HAS_CONFIG = Boolean(url && anon);
