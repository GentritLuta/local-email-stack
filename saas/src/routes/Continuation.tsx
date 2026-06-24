import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getSubmission, getContinuationForSubmission, signContract, Contract, Submission,
  downloadContractHtml, openContractForPrint,
} from "../lib/api";

// The continuation agreement that follows the 3-month pilot. Signing it unlocks
// the billing-on-file step (the pilot itself is billing-free).
export default function Continuation() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sub, setSub] = useState<Submission | null>(null);
  const [contract, setContract] = useState<Contract | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [agree, setAgree] = useState(false);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    async function load() {
      try {
        const s = await getSubmission(id!);
        if (alive) setSub(s);
        const c = await getContinuationForSubmission(id!);
        if (!alive) return;
        setContract(c);
        if (c) {
          setName((p) => p || c.signer_name || "");
          setTitle((p) => p || c.signer_title || "");
          setEmail((p) => p || c.signer_email || s?.raw_answers?.contact_email || "");
        }
        setLoading(false);
      } catch (e: any) {
        if (alive) { setErr(e?.message || String(e)); setLoading(false); }
      }
    }
    load();
    return () => { alive = false; };
  }, [id]);

  async function doSign() {
    if (!contract) return;
    setErr(null); setSigning(true);
    try {
      await signContract(contract.id, {
        signer_name: name.trim(), signer_email: email.trim(), signer_title: title.trim(),
      });
      nav(`/billing/${id}`);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSigning(false);
    }
  }

  const company = sub?.raw_answers?.company || "your company";
  const canSign = !!contract && name.trim().length > 1 && email.trim().includes("@")
    && agree && !signing;

  if (contract?.status === "signed" || contract?.status === "sealed") {
    return (
      <div className="card">
        <h2>Continuation agreement signed</h2>
        <p className="sub">
          Thanks{contract.signer_name ? `, ${contract.signer_name}` : ""}. Next, add your
          billing details so we can continue your campaign.
        </p>
        <button className="btn" onClick={() => nav(`/billing/${id}`)}>Continue to billing</button>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Sign your continuation agreement</h2>
      <p className="sub">
        Your pilot with AUREON Global is complete. To continue, review and sign this
        continuation agreement for {company}. After signing you'll add billing details.
      </p>

      {err && <div className="banner">{err}</div>}
      {loading && !contract && (
        <div className="banner">Loading your continuation agreement…</div>
      )}
      {!loading && !contract && (
        <div className="banner">
          No continuation agreement is ready for you yet. If you expected one, contact AUREON.
        </div>
      )}

      {contract && (
        <>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", margin: "4px 0 0" }}>
            <button className="btn ghost" style={{ marginTop: 0, padding: "8px 14px", fontSize: 12.5 }}
              onClick={() => openContractForPrint(contract)}>Open full page</button>
            <button className="btn ghost" style={{ marginTop: 0, padding: "8px 14px", fontSize: 12.5 }}
              onClick={() => downloadContractHtml(contract)}>Download a copy</button>
          </div>
          <div className="doc-viewer">
            <iframe title="continuation agreement" srcDoc={contract.contract_html} />
          </div>

          <div className="row">
            <div>
              <label>Your full legal name *</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Doe" />
            </div>
            <div>
              <label>Title *</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Owner" />
            </div>
          </div>
          <label>Email *</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />

          <label className="consent" style={{ marginTop: 16 }}>
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              I have read this continuation agreement and agree to be legally bound by it.
              I adopt my typed name above as my electronic signature.
            </span>
          </label>

          <button className="btn block" disabled={!canSign} onClick={doSign} style={{ marginTop: 16 }}>
            {signing ? "Signing…" : "Sign continuation agreement"}
          </button>
          {!canSign && !signing && (
            <div className="hint">Enter your name and email, and check the box to sign.</div>
          )}
        </>
      )}
    </div>
  );
}
