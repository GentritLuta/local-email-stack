import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getSubmission, getContractForSubmission, submitCredentials,
  CredentialsInput, Submission, Contract,
} from "../lib/api";

// Authorization the client adopts as an e-signature when handing over access.
// The text adapts to what they actually grant (email infra, social accounts, or both).
const AUTH_EMAIL =
  "set up and operate my email-sending infrastructure (DNS records, sending subdomains, " +
  "authentication, and deliverability)";
const AUTH_SOCIAL =
  "access and operate the social media accounts I list below, through the platforms' " +
  "business tools, to plan, create, schedule, and publish content and to manage comments " +
  "and direct messages on my behalf";
const AUTH_TAIL =
  " for the duration of our engagement. I confirm I am authorized to grant this access, " +
  "that I can revoke it at any time, and I adopt this confirmation as my electronic signature.";

function authTextFor(isEmail: boolean, isSocial: boolean): string {
  const what = isEmail && isSocial
    ? `${AUTH_EMAIL}, and to ${AUTH_SOCIAL}`
    : isSocial ? AUTH_SOCIAL : AUTH_EMAIL;
  return `I authorize AUREON Global to ${what}${AUTH_TAIL}`;
}

const HOST_LABEL: Record<string, string> = {
  hostinger: "Hostinger",
  cloudflare: "Cloudflare",
  other: "Other",
};

export default function Access() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sub, setSub] = useState<Submission | null>(null);
  const [contract, setContract] = useState<Contract | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [f, setF] = useState<CredentialsInput>({
    registrar: "", dns_host: "hostinger", api_token: "", other_access: "",
    social_handles: "", social_access_confirmed: false, social_business_id: "",
    asset_link: "", content_approver: "",
    notes: "", authorized: false, authorization_text: "",
  });

  // Which access we need depends on the service the client signed up for.
  const svc = ((sub?.raw_answers as any)?.service_type as string) || "email";
  const isEmail = svc === "email" || svc === "both" || svc === "";
  const isSocial = svc === "social" || svc === "both";

  useEffect(() => {
    if (!id) return;
    getSubmission(id).then((s) => {
      setSub(s);
      const a = (s.raw_answers || {}) as any;
      const stype = (a.service_type as string) || "email";
      const wantEmail = stype === "email" || stype === "both" || stype === "";
      const wantSocial = stype === "social" || stype === "both";
      const host = (a.dns_host as string) || "hostinger";
      const handles = [a.platforms, a.handles].filter(Boolean).join(" / ");
      setF((p) => ({
        ...p,
        dns_host: p.dns_host || host,
        registrar: p.registrar || HOST_LABEL[host] || "",
        social_handles: p.social_handles || handles,
        authorization_text: authTextFor(wantEmail, wantSocial),
      }));
    }).catch((e) => setErr(e?.message || String(e)));
    // Access opens only after the pilot agreement is signed.
    getContractForSubmission(id)
      .then((c) => { setContract(c); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [id]);

  const signed = !!contract && (contract.status === "signed" || contract.status === "sealed");

  const set = (k: keyof CredentialsInput) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setF((p) => ({ ...p, [k]: e.target.value }));

  const emailOK = !isEmail || (f.api_token.trim().length > 6 && f.registrar.trim().length > 1);
  const socialOK = !isSocial ||
    (f.social_handles.trim().length > 2 && f.social_access_confirmed && f.asset_link.trim().length > 3);
  const canSave = !saving && f.authorized && emailOK && socialOK;

  async function save() {
    if (!id) return;
    setErr(null); setSaving(true);
    try {
      await submitCredentials(id, { ...f, authorization_text: authTextFor(isEmail, isSocial) });
      nav(`/status/${id}`);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  const company = (sub?.raw_answers as any)?.company || "your company";

  // Gate: access handover is only available after the agreement is signed.
  if (loaded && !signed) {
    return (
      <div className="card">
        <div className="eyebrow">Connect your setup</div>
        <h2>Sign your agreement first</h2>
        <p className="sub">
          This step opens after you sign your service agreement. Sign it and you'll
          be brought back here automatically.
        </p>
        {contract
          ? <button className="btn" onClick={() => nav(`/sign/${id}`)}>Go to your agreement</button>
          : <div className="banner">Your agreement is being prepared. We'll bring you here once it's ready.</div>}
      </div>
    );
  }

  const eyebrow = isEmail && isSocial ? "Connect your accounts and sending"
    : isSocial ? "Connect your social accounts" : "Connect your sending setup";
  const intro = isEmail && isSocial
    ? "Your agreement is signed. To run your accounts and your sending automatically, we need access to your social accounts (through the platforms' business tools) and a scoped API token for your sending domain's DNS. Never share an account password."
    : isSocial
      ? "Your agreement is signed. To run your accounts we need access through the platforms' business tools, your brand assets, and the accounts you want us to manage. We never ask for an account password."
      : "Your agreement is signed. To set up your sending domains, DNS, and deliverability automatically, we need a scoped API token for the host where your sending domain's DNS lives. Please do not enter an account password.";

  return (
    <div className="card">
      <div className="eyebrow">{eyebrow}</div>
      <h2>Give us access to run {company}</h2>
      <p className="sub">{intro}</p>

      {err && <div className="banner">{err}</div>}

      {isSocial && (
        <>
          <h3 style={{ marginTop: 6 }}>Social accounts</h3>
          <label>Accounts to manage *</label>
          <textarea value={f.social_handles} onChange={set("social_handles")}
            placeholder="Instagram @yourbrand, TikTok @yourbrand, Facebook /yourbrand" />

          <label>Grant us access *</label>
          <div className="hint" style={{ marginTop: 2 }}>
            Instagram &amp; Facebook: in <b>Meta Business Suite</b> add <b>info@aureonglobal.de</b> (or
            Aureon Global as a Partner) with content and community-management permissions.
            TikTok: in <b>TikTok Business Center</b> invite <b>info@aureonglobal.de</b> as a Member.
            This grants access without sharing your password, and you can remove it any time.
          </div>
          <label className="consent" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={f.social_access_confirmed}
              onChange={(e) => setF((p) => ({ ...p, social_access_confirmed: e.target.checked }))} />
            <span>I have granted Aureon Global access to manage these accounts through the
              platforms' business tools. No password has been shared.</span>
          </label>

          <label style={{ marginTop: 12 }}>Business account ID or invited email</label>
          <input value={f.social_business_id} onChange={set("social_business_id")}
            placeholder="Meta Business / TikTok Business Center ID, or the email you invited (optional)" />

          <label>Brand assets *</label>
          <input value={f.asset_link} onChange={set("asset_link")}
            placeholder="Link to logo, brand guidelines, product photos, and video footage (Drive, Dropbox, WeTransfer)" />
          <div className="hint">
            We supply the graphics and videos. We just need your logo, brand rules, product shots,
            and any footage you have so everything is on-brand.
          </div>

          <label>Content approver</label>
          <input value={f.content_approver} onChange={set("content_approver")}
            placeholder="Who approves the content calendar? Name and email" />
        </>
      )}

      {isEmail && (
        <>
          <h3 style={{ marginTop: isSocial ? 18 : 6 }}>Sending infrastructure</h3>
          <div className="row">
            <div>
              <label>DNS / domain host *</label>
              <select value={f.dns_host} onChange={set("dns_host")}>
                <option value="hostinger">Hostinger</option>
                <option value="cloudflare">Cloudflare</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label>Provider name *</label>
              <input value={f.registrar} onChange={set("registrar")} placeholder="Hostinger / Cloudflare / GoDaddy" />
            </div>
          </div>

          <label>API token *</label>
          <input type="password" value={f.api_token} onChange={set("api_token")}
            placeholder="Paste your scoped API token (not your password)" autoComplete="off" />
          <div className="hint">
            Hostinger: Account → API → create token. Cloudflare: My Profile → API Tokens → Edit zone DNS.
            A scoped DNS token is all we need.
          </div>

          <label>Other access we should know about</label>
          <textarea value={f.other_access}
            onChange={set("other_access")}
            placeholder="e.g. a second domain on a different host, an existing Resend account, a mailbox to forward replies to." />
        </>
      )}

      <label>Anything else?</label>
      <textarea value={f.notes} onChange={set("notes")} placeholder="Notes, constraints, anything we should know." />

      <h3 style={{ marginTop: 18 }}>Authorization</h3>
      <label className="consent" style={{ marginTop: 6 }}>
        <input type="checkbox" checked={f.authorized}
          onChange={(e) => setF((p) => ({ ...p, authorized: e.target.checked }))} />
        <span>{authTextFor(isEmail, isSocial)}</span>
      </label>

      <button className="btn block" disabled={!canSave} onClick={save} style={{ marginTop: 16 }}>
        {saving ? "Saving…" : "Authorize & connect"}
      </button>
      {!canSave && !saving && (
        <div className="hint">
          {isSocial && !socialOK
            ? "List your accounts, confirm you've granted access, add your brand-assets link, and check the authorization."
            : isEmail && !emailOK
              ? "Pick your host, paste a scoped API token, and check the authorization to continue."
              : "Check the authorization to continue."}
        </div>
      )}
      <div className="hint" style={{ marginTop: 10 }}>
        Your access details are stored securely and used only to run your engagement.
        A copy of this authorization (with timestamp) is kept on file.
      </div>
    </div>
  );
}
