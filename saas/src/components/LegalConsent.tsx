// Three required legal acceptances (Terms & Conditions, Privacy, AGB), each with
// a link to the page on aureonglobal.de and an ⓘ tooltip explaining what it is +
// where to find it. Used on both the onboarding form and the signing screen.

export type LegalAcceptance = { terms: boolean; privacy: boolean; agb: boolean };

const SITE = "https://aureonglobal.de";

const ITEMS: Array<{
  key: keyof LegalAcceptance; label: string; path: string; what: string;
}> = [
  {
    key: "terms", label: "Terms & Conditions", path: "/terms",
    what: "The rules of working with AUREON Global: scope, responsibilities, and how the engagement runs.",
  },
  {
    key: "privacy", label: "Privacy Policy", path: "/privacy",
    what: "How AUREON Global collects, uses, and protects your data, in line with GDPR.",
  },
  {
    key: "agb", label: "AGB", path: "/agb",
    what: "The general terms and conditions (Allgemeine Geschäftsbedingungen) governing the contract under German law.",
  },
];

function InfoTip({ what, path }: { what: string; path: string }) {
  return (
    <span className="info-icon" tabIndex={0} role="button"
      aria-label={`${what} Find it at aureonglobal.de${path}`}>
      i
      <span className="tip">
        {what}
        <br />
        <span style={{ color: "var(--accent)" }}>Find it at aureonglobal.de{path}</span>
      </span>
    </span>
  );
}

export default function LegalConsent({
  value, onChange,
}: { value: LegalAcceptance; onChange: (v: LegalAcceptance) => void }) {
  return (
    <div style={{ marginTop: 4 }}>
      {ITEMS.map((it) => (
        <label className="consent" key={it.key}>
          <input
            type="checkbox"
            checked={value[it.key]}
            onChange={(e) => onChange({ ...value, [it.key]: e.target.checked })}
          />
          <span>
            I accept the{" "}
            <a href={`${SITE}${it.path}`} target="_blank" rel="noreferrer">{it.label}</a>
            <InfoTip what={it.what} path={it.path} />
          </span>
        </label>
      ))}
    </div>
  );
}

export const allAccepted = (v: LegalAcceptance) => v.terms && v.privacy && v.agb;
