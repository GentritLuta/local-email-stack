import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  getCampaignMetrics, CampaignMetrics,
  getContractForClient, Contract, downloadContractHtml, openContractForPrint,
  getInvoices, Invoice, getSales, Sale,
  getReplyOutcomes, ReplyOutcome, getOutreachReport, OutreachReport,
  getBillingForClient, BillingProfile, BillingEditable, updateMyBilling,
} from "../lib/api";

const fmt = (n: number) => n.toLocaleString();
const money = (cents: number, ccy = "EUR") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(cents / 100);

type Tab = "overview" | "replies" | "sales" | "invoices" | "agreement" | "billing";

export default function Dashboard() {
  const { slug } = useParams();
  const [m, setM] = useState<CampaignMetrics | null>(null);
  const [report, setReport] = useState<OutreachReport | null>(null);
  const [outcomes, setOutcomes] = useState<ReplyOutcome[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [contract, setContract] = useState<Contract | null>(null);
  const [billing, setBilling] = useState<BillingProfile | null>(null);
  const [editingBilling, setEditingBilling] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!slug) return;
    let alive = true;
    async function load() {
      try {
        const [mm, rep, oc, inv, sl] = await Promise.all([
          getCampaignMetrics(slug!), getOutreachReport(slug!), getReplyOutcomes(slug!),
          getInvoices(slug!), getSales(slug!),
        ]);
        if (!alive) return;
        setM(mm); setReport(rep); setOutcomes(oc); setInvoices(inv); setSales(sl); setErr(null);
      } catch (e: any) { if (alive) setErr(e?.message || String(e)); }
    }
    load();
    getContractForClient().then((c) => alive && setContract(c)).catch(() => {});
    getBillingForClient().then((b) => alive && setBilling(b)).catch(() => {});
    const iv = setInterval(load, 20000);
    return () => { alive = false; clearInterval(iv); };
  }, [slug]);

  const wonCents = sales.filter((s) => s.status === "won").reduce((a, s) => a + s.amount_cents, 0);
  const pipeCents = sales.filter((s) => s.status === "pipeline").reduce((a, s) => a + s.amount_cents, 0);
  const outstanding = invoices.filter((i) => i.status !== "paid" && i.status !== "void")
    .reduce((a, i) => a + (i.due_cents ?? i.amount_cents), 0);

  const ql = q.trim().toLowerCase();
  const fOutcomes = useMemo(() => !ql ? outcomes :
    outcomes.filter((o) => (o.from + o.subject + o.outcome).toLowerCase().includes(ql)), [outcomes, ql]);
  const fSales = useMemo(() => !ql ? sales :
    sales.filter((s) => ((s.prospect_email || "") + (s.note || "") + s.status).toLowerCase().includes(ql)), [sales, ql]);
  const fInvoices = useMemo(() => !ql ? invoices :
    invoices.filter((i) => (i.invoice_ref + (i.title || "") + i.status).toLowerCase().includes(ql)), [invoices, ql]);

  const TABS: Array<{ k: Tab; label: string; badge?: number }> = [
    { k: "overview", label: "Overview" },
    { k: "replies", label: "Replies", badge: outcomes.length },
    { k: "sales", label: "Sales", badge: sales.length },
    { k: "invoices", label: "Invoices", badge: invoices.length },
    { k: "agreement", label: "Agreement" },
    { k: "billing", label: "Billing" },
  ];

  return (
    <>
      <div className="card">
        <div className="eyebrow">Client dashboard</div>
        <h2>Your campaign &amp; account</h2>
        <p className="sub">Live for {slug}. Refreshes automatically.</p>
        {err && <div className="banner">⚠ {err}</div>}

        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.k} className={`tab ${tab === t.k ? "active" : ""}`} onClick={() => { setTab(t.k); setQ(""); }}>
              {t.label}{typeof t.badge === "number" && t.badge > 0 ? <span className="badge">{t.badge}</span> : null}
            </button>
          ))}
        </div>

        {/* ── Overview ── */}
        {tab === "overview" && (
          <>
            <div className="metrics" style={{ marginBottom: 14 }}>
              <Metric big={fmt(m?.leads ?? 0)} lbl="Verified leads" />
              <Metric big={fmt(m?.enrolled ?? 0)} lbl="In sequence" />
              <Metric big={fmt(m?.sentTotal ?? 0)} lbl="Emails sent" />
            </div>
            <div className="metrics" style={{ marginBottom: 18 }}>
              <Metric big={`${m?.deliveredPct ?? 0}%`} lbl="Delivered" />
              <Metric big={fmt(m?.replies ?? 0)} lbl="Replies" />
              <Metric big={fmt(m?.conversations ?? 0)} lbl="Live conversations" />
            </div>
            <h3 style={{ marginTop: 6 }}>Outreach report</h3>
            <div className="kpi-row">
              <Kpi v={fmt(report?.sent ?? 0)} k="Sent" />
              <Kpi v={`${report?.deliveredPct ?? 0}%`} k="Delivered" gold />
              <Kpi v={`${report?.bouncePct ?? 0}%`} k="Bounced" />
              <Kpi v={`${report?.replyPct ?? 0}%`} k="Reply rate" gold />
            </div>
            <Bar label="Delivered" pct={report?.deliveredPct ?? 0} />
            <div className="hint" style={{ marginTop: 10 }}>
              By step:{" "}
              {report && Object.keys(report.byStep).length
                ? Object.entries(report.byStep).sort().map(([s, n]) => `step ${s}: ${n}`).join(" · ")
                : "no sends yet"}
            </div>
          </>
        )}

        {/* ── Replies & outcomes ── */}
        {tab === "replies" && (
          <>
            <Search q={q} setQ={setQ} placeholder="Search replies…" />
            {fOutcomes.length === 0 ? <div className="empty">No replies match.</div> : (
              <table className="tbl">
                <thead><tr><th>From</th><th>Subject</th><th>When</th><th>Outcome</th></tr></thead>
                <tbody>
                  {fOutcomes.map((o, i) => (
                    <tr key={i}>
                      <td>{o.from}</td>
                      <td>{o.subject || "(no subject)"}</td>
                      <td>{o.at?.slice(0, 10)}</td>
                      <td><span className={`pill ${o.outcome.toLowerCase().includes("book") ? "booked" : "replied"}`}>{o.outcome}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {/* ── Sales ── */}
        {tab === "sales" && (
          <>
            <div className="kpi-row">
              <Kpi v={money(wonCents)} k="Revenue won" gold />
              <Kpi v={money(pipeCents)} k="In pipeline" />
              <Kpi v={fmt(sales.filter((s) => s.status === "won").length)} k="Deals won" />
            </div>
            <Search q={q} setQ={setQ} placeholder="Search sales…" />
            {fSales.length === 0 ? <div className="empty">No sales match.</div> : (
              <table className="tbl">
                <thead><tr><th>Prospect</th><th>Status</th><th className="num">Amount</th><th>Closed</th></tr></thead>
                <tbody>
                  {fSales.map((s) => (
                    <tr key={s.id}>
                      <td>{s.prospect_email || s.note || "—"}</td>
                      <td><span className={`pill ${s.status}`}>{s.status}</span></td>
                      <td className="num">{money(s.amount_cents, s.currency)}</td>
                      <td>{s.closed_at?.slice(0, 10) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {/* ── Invoices ── */}
        {tab === "invoices" && (
          <>
            {outstanding > 0 && <div className="kpi-row"><Kpi v={money(outstanding)} k="Outstanding" /></div>}
            <Search q={q} setQ={setQ} placeholder="Search invoices…" />
            {fInvoices.length === 0 ? <div className="empty">No invoices match.</div> : (
              <table className="tbl">
                <thead><tr><th>Invoice</th><th>Status</th><th className="num">Amount</th><th>Issued</th></tr></thead>
                <tbody>
                  {fInvoices.map((inv) => (
                    <tr key={inv.id}>
                      <td>{inv.invoice_ref}{inv.title ? <div className="hint" style={{ margin: 0 }}>{inv.title.slice(0, 50)}</div> : null}</td>
                      <td><span className={`pill ${inv.status}`}>{inv.status}</span></td>
                      <td className="num">{money(inv.amount_cents, inv.currency)}</td>
                      <td>{inv.issued_at || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {/* ── Agreement ── */}
        {tab === "agreement" && (
          <>
            {contract ? (
              <>
                <p className="hint" style={{ marginBottom: 14 }}>
                  {contract.status === "sealed" || contract.status === "signed"
                    ? `Signed and on file (${contract.contract_ref}). Available any time.`
                    : `Draft prepared (${contract.contract_ref}).`}
                </p>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button className="btn secondary" style={{ marginTop: 0 }} onClick={() => openContractForPrint(contract)}>View agreement</button>
                  <button className="btn ghost" style={{ marginTop: 0 }} onClick={() => downloadContractHtml(contract)}>Download</button>
                </div>
              </>
            ) : <div className="empty">No agreement on file yet.</div>}
          </>
        )}

        {/* ── Billing ── */}
        {tab === "billing" && (
          <>
            {billing && billing.authorized ? (
              editingBilling ? (
                <BillingEditForm
                  billing={billing}
                  onCancel={() => setEditingBilling(false)}
                  onSaved={async () => {
                    setEditingBilling(false);
                    const b = await getBillingForClient().catch(() => null);
                    if (b) setBilling(b);
                  }}
                />
              ) : (
                <>
                  <p className="hint" style={{ marginBottom: 14 }}>
                    Charge authorization on file{billing.authorized_at ? ` since ${billing.authorized_at.slice(0, 10)}` : ""}.
                    Charges run via Payoneer or your funding method.
                  </p>
                  <table className="tbl">
                    <tbody>
                      <tr><td>Billing name</td><td>{billing.billing_name || "—"}</td></tr>
                      <tr><td>Legal name</td><td>{billing.legal_name || "—"}</td></tr>
                      <tr><td>Billing email</td><td>{billing.billing_email || "—"}</td></tr>
                      <tr><td>Address</td><td>{[billing.address_line, billing.postal_code, billing.city].filter(Boolean).join(", ") || "—"}</td></tr>
                      <tr><td>Country</td><td>{billing.country || "—"}</td></tr>
                      <tr><td>VAT / tax ID</td><td>{billing.vat_id || "—"}</td></tr>
                      <tr><td>Funding</td><td>{billing.payoneer_email || billing.iban || "—"}</td></tr>
                      {billing.payoneer_status && <tr><td>Last charge</td><td><span className="pill">{billing.payoneer_status}</span></td></tr>}
                    </tbody>
                  </table>
                  <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                    <button className="btn secondary" style={{ marginTop: 0 }} onClick={() => setEditingBilling(true)}>
                      Edit billing details
                    </button>
                  </div>
                  <div className="hint" style={{ marginTop: 10 }}>
                    Your card itself is managed in Payoneer. Update your billing address, funding
                    email/IBAN, and company details here any time.
                  </div>
                </>
              )
            ) : (
              <div className="empty">
                No billing on file yet. After signing your agreement you can add billing details.
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

function BillingEditForm({ billing, onCancel, onSaved }:
  { billing: BillingProfile; onCancel: () => void; onSaved: () => void }) {
  const [f, setF] = useState<BillingEditable>({
    billing_name: billing.billing_name || "",
    legal_name: billing.legal_name || "",
    billing_email: billing.billing_email || "",
    address_line: billing.address_line || "",
    city: billing.city || "",
    postal_code: billing.postal_code || "",
    country: billing.country || "",
    vat_id: billing.vat_id || "",
    payoneer_email: billing.payoneer_email || "",
    iban: billing.iban || "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof BillingEditable) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));

  const hasFunding = !!(f.payoneer_email.trim() || f.iban.trim());
  const canSave = !saving && hasFunding
    && f.billing_email.trim().includes("@") && f.country.trim().length > 1;

  async function save() {
    setErr(null); setSaving(true);
    try {
      await updateMyBilling(billing.id, f);
      onSaved();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <p className="hint" style={{ marginBottom: 14 }}>
        Update your billing details. Your charge authorization stays in place; your card
        itself is managed in Payoneer.
      </p>
      {err && <div className="banner">{err}</div>}
      <div className="row">
        <div><label>Billing contact name</label>
          <input value={f.billing_name} onChange={set("billing_name")} placeholder="Jane Doe" /></div>
        <div><label>Company legal name</label>
          <input value={f.legal_name} onChange={set("legal_name")} placeholder="Acme GmbH" /></div>
      </div>
      <label>Billing email *</label>
      <input value={f.billing_email} onChange={set("billing_email")} placeholder="billing@company.com" />
      <label>Billing address</label>
      <input value={f.address_line} onChange={set("address_line")} placeholder="Street and number" />
      <div className="row">
        <div><label>City</label><input value={f.city} onChange={set("city")} placeholder="Berlin" /></div>
        <div><label>Postal code</label><input value={f.postal_code} onChange={set("postal_code")} placeholder="10115" /></div>
      </div>
      <div className="row">
        <div><label>Country *</label><input value={f.country} onChange={set("country")} placeholder="Germany" /></div>
        <div><label>VAT / tax ID</label><input value={f.vat_id} onChange={set("vat_id")} placeholder="DE123456789" /></div>
      </div>
      <h3 style={{ marginTop: 14 }}>Funding method</h3>
      <div className="row">
        <div><label>Payoneer email</label>
          <input value={f.payoneer_email} onChange={set("payoneer_email")} placeholder="you@payoneer-linked.com" /></div>
        <div><label>IBAN</label>
          <input value={f.iban} onChange={set("iban")} placeholder="DE00 0000 0000 0000 0000 00" /></div>
      </div>
      {!hasFunding && <div className="hint">Add a Payoneer email or an IBAN.</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn" style={{ marginTop: 0 }} disabled={!canSave} onClick={save}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button className="btn ghost" style={{ marginTop: 0 }} disabled={saving} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </>
  );
}

function Search({ q, setQ, placeholder }: { q: string; setQ: (s: string) => void; placeholder: string }) {
  return (
    <div className="search">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} />
    </div>
  );
}
function Metric({ big, lbl }: { big: string; lbl: string }) {
  return <div className="metric"><div className="big">{big}</div><div className="lbl">{lbl}</div></div>;
}
function Kpi({ v, k, gold }: { v: string; k: string; gold?: boolean }) {
  return <div className="kpi"><div className={`v ${gold ? "gold" : ""}`}>{v}</div><div className="k">{k}</div></div>;
}
function Bar({ label, pct }: { label: string; pct: number }) {
  return (
    <div>
      <div className="hint" style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{label}</span><span>{pct}%</span>
      </div>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, pct)}%` }} /></div>
    </div>
  );
}
