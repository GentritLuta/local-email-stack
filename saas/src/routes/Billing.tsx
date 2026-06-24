import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getSubmission, submitBilling, BillingInput, Submission,
  getContinuationForSubmission, Contract,
} from "../lib/api";

// General charge-authorization wording (kept broad per request — not tied to
// "agreed invoices"). This exact text is hashed + stored as the signed mandate.
const AUTH_TEXT =
  "I authorize AUREON Global to charge me, via Payoneer or the payment method " +
  "and billing details I have provided, for services rendered. I confirm I am " +
  "authorized to permit charges on this account, and I adopt this confirmation " +
  "as my electronic signature.";

export default function Billing() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sub, setSub] = useState<Submission | null>(null);
  const [cont, setCont] = useState<Contract | null>(null);
  const [contLoaded, setContLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [f, setF] = useState<BillingInput>({
    billing_name: "", legal_name: "", billing_email: "",
    address_line: "", city: "", postal_code: "", country: "",
    vat_id: "", payoneer_email: "", iban: "",
    authorized: false, authorization_text: AUTH_TEXT,
  });

  useEffect(() => {
    if (!id) return;
    getSubmission(id).then((s) => {
      setSub(s);
      const a = s.raw_answers || ({} as any);
      setF((p) => ({
        ...p,
        legal_name: p.legal_name || a.company || "",
        billing_email: p.billing_email || a.contact_email || "",
        billing_name: p.billing_name || a.rep || "",
      }));
    }).catch((e) => setErr(e?.message || String(e)));
    // Billing unlocks only after the continuation agreement is signed.
    getContinuationForSubmission(id)
      .then((c) => { setCont(c); setContLoaded(true); })
      .catch(() => setContLoaded(true));
  }, [id]);

  const continuationSigned = !!cont && (cont.status === "signed" || cont.status === "sealed");

  const set = (k: keyof BillingInput) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));

  const hasFunding = !!(f.payoneer_email?.trim() || f.iban?.trim());
  const canSave = !saving && f.authorized && hasFunding
    && f.billing_name.trim().length > 1 && f.legal_name.trim().length > 1
    && f.billing_email.trim().includes("@") && f.country.trim().length > 1;

  async function save() {
    if (!id) return;
    setErr(null); setSaving(true);
    try {
      await submitBilling(id, f);
      nav(`/status/${id}`);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  const company = sub?.raw_answers?.company || "your company";

  // Gate: billing is only available after the continuation agreement is signed.
  if (contLoaded && !continuationSigned) {
    return (
      <div className="card">
        <div className="eyebrow">Billing on file</div>
        <h2>Sign your continuation agreement first</h2>
        <p className="sub">
          Billing setup opens after you sign your continuation agreement. If you have
          one ready, sign it and you'll be brought back here automatically.
        </p>
        {cont
          ? <button className="btn" onClick={() => nav(`/continuation/${id}`)}>Go to continuation agreement</button>
          : <div className="banner">No continuation agreement is ready yet. We'll email you when it is.</div>}
      </div>
    );
  }

  return (
    <div className="card">
      <div className="eyebrow">Billing on file</div>
      <h2>Set up billing for {company}</h2>
      <p className="sub">
        Your continuation agreement is signed. Add your billing details so we can
        invoice and charge for services. Your card number is never stored by us;
        charges run through Payoneer or the funding method you provide below.
      </p>

      {err && <div className="banner">{err}</div>}

      <h3 style={{ marginTop: 8 }}>Billing identity</h3>
      <div className="row">
        <div>
          <label>Billing contact name *</label>
          <input value={f.billing_name} onChange={set("billing_name")} placeholder="Jane Doe" />
        </div>
        <div>
          <label>Company legal name *</label>
          <input value={f.legal_name} onChange={set("legal_name")} placeholder="Acme GmbH" />
        </div>
      </div>
      <label>Billing email *</label>
      <input value={f.billing_email} onChange={set("billing_email")} placeholder="billing@company.com" />
      <label>Billing address</label>
      <input value={f.address_line} onChange={set("address_line")} placeholder="Street and number" />
      <div className="row">
        <div>
          <label>City</label>
          <input value={f.city} onChange={set("city")} placeholder="Berlin" />
        </div>
        <div>
          <label>Postal code</label>
          <input value={f.postal_code} onChange={set("postal_code")} placeholder="10115" />
        </div>
      </div>
      <div className="row">
        <div>
          <label>Country *</label>
          <input value={f.country} onChange={set("country")} placeholder="Germany" />
        </div>
        <div>
          <label>VAT / tax ID</label>
          <input value={f.vat_id} onChange={set("vat_id")} placeholder="DE123456789" />
        </div>
      </div>

      <h3 style={{ marginTop: 18 }}>Funding method</h3>
      <p className="hint" style={{ marginTop: 0 }}>
        Give at least one. We charge via Payoneer; a Payoneer email is fastest.
      </p>
      <div className="row">
        <div>
          <label>Payoneer email</label>
          <input value={f.payoneer_email} onChange={set("payoneer_email")} placeholder="you@payoneer-linked.com" />
        </div>
        <div>
          <label>IBAN (optional)</label>
          <input value={f.iban} onChange={set("iban")} placeholder="DE00 0000 0000 0000 0000 00" />
        </div>
      </div>
      {!hasFunding && (
        <div className="hint">Add a Payoneer email or an IBAN so we can charge.</div>
      )}

      <h3 style={{ marginTop: 18 }}>Charge authorization</h3>
      <label className="consent" style={{ marginTop: 6 }}>
        <input type="checkbox" checked={f.authorized}
          onChange={(e) => setF((p) => ({ ...p, authorized: e.target.checked }))} />
        <span>{AUTH_TEXT}</span>
      </label>

      <button className="btn block" disabled={!canSave} onClick={save} style={{ marginTop: 16 }}>
        {saving ? "Saving…" : "Authorize & save billing"}
      </button>
      {!canSave && !saving && (
        <div className="hint">Fill the required fields, add a funding method, and check the authorization to continue.</div>
      )}
      <div className="hint" style={{ marginTop: 10 }}>
        A copy of this authorization (with timestamp) is kept on file. You can
        update billing any time from your dashboard.
      </div>
    </div>
  );
}
