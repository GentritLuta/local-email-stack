import { useEffect, useState } from "react";
import { ChevronDown, UserRound } from "lucide-react";
import { Profile, getActiveSlug, loadAllProfiles, setActiveSlug } from "../lib/profiles";

export function ProfilePicker() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [active, setActive] = useState<string | null>(getActiveSlug());
  const [open, setOpen] = useState(false);

  useEffect(() => {
    (async () => {
      const all = await loadAllProfiles();
      setProfiles(all);
      if (!active && all.length > 0) {
        setActiveSlug(all[0].slug);
        setActive(all[0].slug);
      }
    })();
    const h = (e: Event) => setActive((e as CustomEvent).detail);
    window.addEventListener("active-profile-changed", h);
    return () => window.removeEventListener("active-profile-changed", h);
  }, []);

  const current = profiles.find(p => p.slug === active) ?? profiles[0];

  return (
    <div style={{ position: "relative", marginBottom: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "8px 10px", justifyContent: "space-between",
          background: "var(--bg-2)", border: "var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
          <UserRound size={14} />
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <div style={{ fontSize: 12, color: "var(--fg-2)", lineHeight: 1 }}>profile</div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{current?.name ?? "(none)"}</div>
          </div>
        </div>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10,
          marginTop: 4, background: "var(--bg-1)", border: "var(--border)",
          borderRadius: 8, padding: 4, boxShadow: "var(--shadow)",
        }}>
          {profiles.map(p => (
            <div key={p.slug}
                 onClick={() => { setActiveSlug(p.slug); setActive(p.slug); setOpen(false); }}
                 style={{
                   padding: "8px 10px", borderRadius: 6, cursor: "pointer",
                   background: p.slug === active ? "rgba(34,211,238,0.08)" : undefined,
                 }}>
              <div style={{ fontWeight: 500 }}>{p.name}</div>
              <div style={{ fontSize: 11, color: "var(--fg-2)" }}>{p.identity.from_addr}</div>
              <div style={{ fontSize: 10, marginTop: 2 }}>
                <span className={`pill ${p.relay.domain_verified_at ? "green" : "amber"}`}>
                  {p.relay.domain_verified_at ? "domain verified" : "domain unverified"}
                </span>
                {" "}
                <span className={`pill ${p.warmup.enabled ? "cyan" : ""}`}>
                  {p.warmup.enabled ? `warmup day ${p.warmup.current_day}` : "warmup off"}
                </span>
              </div>
            </div>
          ))}
          <div onClick={() => { setOpen(false); location.hash = "/profiles"; }}
               style={{ padding: "8px 10px", borderRadius: 6, cursor: "pointer", color: "var(--accent-cyan)", borderTop: "var(--border)" }}>
            + Manage profiles…
          </div>
        </div>
      )}
    </div>
  );
}
