import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getSubmission, getContractForSubmission, getContractById, signContract, Contract, Submission,
  downloadContractHtml, openContractForPrint,
} from "../lib/api";
import LegalConsent, { LegalAcceptance, allAccepted } from "../components/LegalConsent";

export default function Sign() {
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
  const [legal, setLegal] = useState<LegalAcceptance>({ terms: false, privacy: false, agb: false });
  const [signing, setSigning] = useState(false);

  // Poll until the PC pipeline has auto-prepared the draft contract.
  useEffect(() => {
    if (!id) return;
    let alive = true;
    let tries = 0;
    async function tick() {
      try {
        // The route param is normally a submission id, but some hand-issued
        // re-sign links carry the contract id instead. Resolve either: look up
        // the contract by submission first, then fall back to contract-by-id
        // (both maybeSingle, so a wrong-type id returns null instead of
        // throwing). Then load the submission from the resolved id.
        let c = await getContractForSubmission(id!);
        let subId = id!;
        if (!c) {
          const byId = await getContractById(id!);
          if (byId) { c = byId; subId = byId.submission_id; }
        }
        const s = await getSubmission(subId);
        if (!alive) return;
        setSub(s);
        if (c) {
          setContract(c);
          setName((p) => p || c.signer_name || "");
          setTitle((p) => p || c.signer_title || "");
          setEmail((p) => p || c.signer_email || s?.raw_answers?.contact_email || "");
          setLoading(false);
          return; // stop polling once we have it
        }
      } catch (e: any) {
        if (alive) setErr(e?.message || String(e));
      }
      tries++;
      if (alive && tries < 40) setTimeout(tick, 3000); // up to ~2 min
      else if (alive) setLoading(false);
    }
    tick();
    return () => { alive = false; };
  }, [id]);

  async function doSign() {
    if (!contract) return;
    setErr(null); setSigning(true);
    try {
      await signContract(contract.id, {
        signer_name: name.trim(),
        signer_email: email.trim(),
        signer_title: title.trim(),
      });
      // After signing, collect the client's sending-infra access so the
      // pipeline can provision automatically, then they land on status. Use the
      // resolved submission id (sub.id), not the raw param, which may be a
      // contract id on older re-sign links.
      nav(`/access/${sub?.id ?? id}`);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSigning(false);
    }
  }

  const company = sub?.raw_answers?.company || "your company";
  const canSign = !!contract && name.trim().length > 1 && email.trim().includes("@")
    && agree && allAccepted(legal) && !signing;

  if (contract?.status === "signed" || contract?.status === "sealed") {
    return (
      <div className="card">
        <h2>Agreement signed</h2>
        <p className="sub">
          Thanks{contract.signer_name ? `, ${contract.signer_name}` : ""}. Your agreement
          ({contract.contract_ref}) is signed. We are now setting up your campaign.
        </p>
        <button className="btn" onClick={() => nav(`/access/${sub?.id ?? id}`)}>Continue setup</button>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Sign your service agreement</h2>
      <p className="sub">
        We prepared this pilot agreement for {company} from the details you submitted.
        Read it, then sign below. Setup begins only after you sign.
      </p>

      {err && <div className="banner">{err}</div>}

      {loading && !contract && (
        <div className="banner">Preparing your agreement from your details… this takes a few seconds.</div>
      )}
      {!loading && !contract && (
        <div className="banner">
          Your agreement is still being prepared. Refresh this page in a minute, or contact us if it persists.
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
            <iframe title="agreement" srcDoc={contract.contract_html} />
          </div>
          <div className="hint" style={{ marginBottom: 14 }}>
            Read, open full-page, or download this agreement before signing. Your signed copy
            stays available in your dashboard afterward.
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
              I have read this agreement and agree to be legally bound by it. I adopt my typed
              name above as my electronic signature.
            </span>
          </label>

          <LegalConsent value={legal} onChange={setLegal} />

          <button className="btn block" disabled={!canSign} onClick={doSign} style={{ marginTop: 16 }}>
            {signing ? "Signing…" : "Sign agreement"}
          </button>
          {!canSign && !signing && (
            <div className="hint">Enter your name and email, and check the box to sign.</div>
          )}
        </>
      )}
    </div>
  );
}
