import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  listClients, inviteClient,
  adminCreateInvoice, adminCreateSale,
  adminListSignedContracts, downloadContractHtml, openContractForPrint,
  adminResetUserEmail, adminResetUser2fa,
  adminListBillingProfiles, BillingProfile,
} from "../lib/api";
import { useAuth } from "../lib/auth";

type Client = {
  id: string; email: string; company: string | null; status: string;
  profile_slug: string | null; created_at: string;
};
type SignedContract = {
  id: string; contract_ref: string; status: string; signer_name: string | null;
  signer_email: string | null; signed_at: string | null; sealed_at: string | null;
  signer_ip: string | null; contract_sha256: string | null; contract_html: string;
};

export default function Admin() {
  const { user, signOut } = useAuth();
  const [clients, setClients] = useState<Client[]>([]);
  const [signed, setSigned] = useState<SignedContract[]>([]);
  const [billing, setBilling] = useState<Array<BillingProfile & { profile_slug: string | null }>>([]);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteCompany, setInviteCompany] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setClients(await listClients());
      setSigned(await adminListSignedContracts());
      setBilling(await adminListBillingProfiles());
    } catch (e: any) {
      setErr(e?.message || String(e));
    }
  }
  useEffect(() => { load(); }, []);

  async function doInvite() {
    setErr(null); setNote(null);
    if (!inviteEmail.includes("@")) { setErr("Enter a valid email."); return; }
    setBusy(true);
    try {
      await inviteClient(inviteEmail.trim(), inviteCompany.trim() || undefined);
      setNote(`Invite sent to ${inviteEmail.trim()}.`);
      setInviteEmail(""); setInviteCompany("");
      await load();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Admin — Clients</h2>
        <span className="hint">{user?.email}</span>
      </div>
      <p className="sub">Invite clients and see everyone in the portal.</p>

      {err && <div className="banner">{err}</div>}
      {note && <div className="banner" style={{ background: "#0f2a1a" }}>{note}</div>}

      <h3 style={{ marginBottom: 4 }}>Invite a client</h3>
      <div className="row">
        <div>
          <label>Email</label>
          <input value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="client@company.com" />
        </div>
        <div>
          <label>Company (optional)</label>
          <input value={inviteCompany} onChange={(e) => setInviteCompany(e.target.value)} placeholder="Company Co" />
        </div>
      </div>
      <button className="btn" disabled={busy || !inviteEmail} onClick={doInvite}>
        {busy ? "Inviting…" : "Send invite"}
      </button>

      <h3 style={{ marginTop: 24, marginBottom: 4 }}>All clients ({clients.length})</h3>
      {clients.length === 0 && <p className="hint">No clients yet.</p>}
      {clients.map((c) => (
        <ClientRow key={c.id} c={c} />
      ))}

      <div style={{ marginTop: 20 }}>
        <button className="btn secondary" onClick={() => signOut()}>Sign out</button>
      </div>
    </div>

    {signed.length > 0 && (
      <div className="card">
        <h3>Signed agreements ({signed.length})</h3>
        <p className="hint" style={{ marginBottom: 12 }}>
          Every signature with its evidence trail: who signed, when, IP, and the SHA-256
          integrity hash. A copy is also emailed to you and the client on signing.
        </p>
        <table className="tbl">
          <thead><tr><th>Agreement</th><th>Signed by</th><th>When (UTC)</th><th>IP</th><th></th></tr></thead>
          <tbody>
            {signed.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.contract_ref}
                  <div className="hint" style={{ margin: 0, fontFamily: "monospace", fontSize: 10 }}>
                    {s.contract_sha256 ? s.contract_sha256.slice(0, 24) + "…" : "—"}
                  </div>
                </td>
                <td>{s.signer_name}<div className="hint" style={{ margin: 0 }}>{s.signer_email}</div></td>
                <td>{(s.signed_at || "").slice(0, 16).replace("T", " ")}</td>
                <td style={{ fontFamily: "monospace", fontSize: 11 }}>{s.signer_ip || "—"}</td>
                <td className="num">
                  <button className="btn ghost" style={{ marginTop: 0, padding: "5px 10px", fontSize: 11 }}
                    onClick={() => openContractForPrint(s as any)}>View</button>{" "}
                  <button className="btn ghost" style={{ marginTop: 0, padding: "5px 10px", fontSize: 11 }}
                    onClick={() => downloadContractHtml(s as any)}>PDF</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}

    {billing.length > 0 && (
      <div className="card">
        <h3>Billing on file ({billing.length})</h3>
        <p className="hint" style={{ marginBottom: 12 }}>
          Signed charge authorizations. Each client profile is dropped to the invoice
          generator and you're emailed on submission. Charges run via Payoneer.
        </p>
        <table className="tbl">
          <thead><tr><th>Client</th><th>Funding</th><th>Authorized (UTC)</th><th>Last charge</th><th>SHA</th></tr></thead>
          <tbody>
            {billing.map((b) => (
              <tr key={b.id}>
                <td>{b.legal_name || b.billing_name || "—"}
                  <div className="hint" style={{ margin: 0 }}>{b.billing_email}</div></td>
                <td>{b.payoneer_email || b.iban || "—"}</td>
                <td>{(b.authorized_at || "").slice(0, 16).replace("T", " ")}</td>
                <td>{b.payoneer_status ? <span className="pill">{b.payoneer_status}</span> : "—"}</td>
                <td style={{ fontFamily: "monospace", fontSize: 10 }}>
                  {b.authorization_sha ? b.authorization_sha.slice(0, 16) + "…" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
    </>
  );
}

function ClientRow({ c }: { c: Client }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [invRef, setInvRef] = useState("");
  const [invAmt, setInvAmt] = useState("");
  const [saleAmt, setSaleAmt] = useState("");
  const [saleNote, setSaleNote] = useState("");
  const [newEmail, setNewEmail] = useState("");

  async function addInvoice() {
    setMsg(null);
    try {
      await adminCreateInvoice({
        client_id: c.id, profile_slug: c.profile_slug ?? undefined,
        invoice_ref: invRef.trim(), amount_cents: Math.round(parseFloat(invAmt || "0") * 100),
        currency: "EUR", status: "sent",
      });
      setMsg("Invoice added."); setInvRef(""); setInvAmt("");
    } catch (e: any) { setMsg(e?.message || String(e)); }
  }
  async function logSale() {
    setMsg(null);
    try {
      await adminCreateSale({
        client_id: c.id, profile_slug: c.profile_slug ?? undefined,
        amount_cents: Math.round(parseFloat(saleAmt || "0") * 100), currency: "EUR",
        status: "won", note: saleNote.trim() || undefined,
      });
      setMsg("Sale logged."); setSaleAmt(""); setSaleNote("");
    } catch (e: any) { setMsg(e?.message || String(e)); }
  }
  async function resetEmail() {
    setMsg(null);
    try {
      await adminResetUserEmail(c.email, newEmail.trim());
      setMsg(`Login email changed to ${newEmail.trim()}.`); setNewEmail("");
    } catch (e: any) { setMsg(e?.message || String(e)); }
  }
  async function reset2fa() {
    setMsg(null);
    try {
      const r = await adminResetUser2fa(c.email);
      setMsg(`2FA reset (${r?.factors_removed ?? 0} removed). They can log in with their password.`);
    } catch (e: any) { setMsg(e?.message || String(e)); }
  }

  return (
    <div className="step" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div className="name">{c.company || "(no company)"} <span className={`pill ${c.status}`}>{c.status}</span></div>
          <div className="hint">{c.email}{c.profile_slug ? ` · ${c.profile_slug}` : ""}</div>
        </div>
        <button className="btn ghost" style={{ marginTop: 0, padding: "7px 12px", fontSize: 12 }} onClick={() => setOpen(!open)}>
          {open ? "Close" : "CRM"}
        </button>
        {c.profile_slug && <Link className="btn secondary" style={{ marginTop: 0, padding: "7px 12px", fontSize: 12 }} to={`/dashboard/${c.profile_slug}`}>Dashboard</Link>}
      </div>
      {open && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--rule)" }}>
          {msg && <div className="hint" style={{ color: "var(--accent)", marginBottom: 8 }}>{msg}</div>}
          <div className="hint" style={{ marginBottom: 8 }}>
            Invoices generated in the AUREON invoice generator import automatically with their
            paid/unpaid status. Use this only to add one by hand.
          </div>
          <div className="row">
            <input placeholder="Invoice ref (AG-…)" value={invRef} onChange={(e) => setInvRef(e.target.value)} />
            <input placeholder="Amount (EUR)" value={invAmt} onChange={(e) => setInvAmt(e.target.value)} />
          </div>
          <button className="btn ghost" style={{ marginTop: 10, padding: "8px 14px", fontSize: 12.5 }} disabled={!invRef || !invAmt} onClick={addInvoice}>Add invoice</button>
          <div className="row" style={{ marginTop: 14 }}>
            <input placeholder="Sale amount (EUR)" value={saleAmt} onChange={(e) => setSaleAmt(e.target.value)} />
            <input placeholder="Note (who / what)" value={saleNote} onChange={(e) => setSaleNote(e.target.value)} />
          </div>
          <button className="btn ghost" style={{ marginTop: 10, padding: "8px 14px", fontSize: 12.5 }} disabled={!saleAmt} onClick={logSale}>Log sale (won)</button>

          <h3 style={{ marginTop: 20, marginBottom: 4 }}>Account recovery</h3>
          <div className="hint" style={{ marginBottom: 8 }}>
            If this client is locked out: change their login email, or remove their 2FA so
            they can sign in with just their password.
          </div>
          <div className="row">
            <input placeholder="New login email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
            <button className="btn ghost" style={{ marginTop: 0, padding: "8px 14px", fontSize: 12.5 }}
              disabled={!newEmail.includes("@")} onClick={resetEmail}>Change email</button>
          </div>
          <button className="btn ghost" style={{ marginTop: 10, padding: "8px 14px", fontSize: 12.5 }}
            onClick={reset2fa}>Reset their 2FA</button>
        </div>
      )}
    </div>
  );
}
