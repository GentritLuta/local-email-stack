import { useParams, useNavigate, Link } from "react-router-dom";

type Explain = {
  title: string;
  tagline: string;
  what: string;
  how: string[];
  results: { k: string; v: string }[];
  examples: string;
};

const EXPLAIN: Record<string, Explain> = {
  email: {
    title: "Email marketing",
    tagline: "Done-for-you cold email that lands in the inbox and gets replies.",
    what:
      "We run the whole cold-email engine for you: we set up your sending infrastructure, source the right people, write the sequence around a free-value offer, send it safely, and handle every reply, so warm leads land in your inbox ready to close.",
    how: [
      "Sending setup. We register sending subdomains separate from your main site and publish the DNS (SPF, DKIM, DMARC), then warm them so your mail reaches the inbox, not spam.",
      "Leads. We source people who match your ideal customer (or load a CSV you provide), verify the addresses, and suppress anyone who should not be contacted.",
      "The sequence. We write a 7-email give-first sequence built around your free-value offer, the single biggest lever on replies, personalized to each prospect.",
      "Sending. Emails go out on a calendar at safe daily volumes from rotating sender personas, with bounce and unsubscribe hygiene running automatically.",
      "Replies. Every reply is read and classified within minutes: positive ones get an instant on-brand answer, your give-first deliverable is sent the moment someone asks for it, and warm leads are forwarded to you with a ready-to-send reply and a short to-do list.",
    ],
    results: [
      { k: "Inbox, not spam", v: "~97% delivered across recent live sends" },
      { k: "Replies handled fast", v: "every reply read and answered within the hour, automatically" },
      { k: "Leads handed to you", v: "warm prospects forwarded with the next step already written" },
    ],
    examples:
      "A roofer's free-value offer is a teardown of where their Google profile is losing calls, sent as a branded PDF the moment they reply AUDIT. A real-estate agent offers a free motivated-seller test in their zip. A SaaS founder offers a list of 40 production edge cases their AI will hit. Each one is a real deliverable we build once and then deliver automatically.",
  },
  social: {
    title: "Social media management",
    tagline: "We run your Instagram and TikTok end to end.",
    what:
      "We plan, create, schedule, and post your content and keep your accounts active and on-brand, so your social presence runs without you having to touch it.",
    how: [
      "Brand intake. We learn your voice, your offer, and your audience from a short brief.",
      "Content. We produce on-brand posts (caption plus visual) tuned to each platform.",
      "Scheduling. Posts go out on a consistent cadence at the times your audience is most active.",
      "Posting. We publish through the official platform APIs, so your accounts stay safe and compliant.",
      "Reporting. You get a monthly report of what went out and how it performed.",
    ],
    results: [
      { k: "Always-on presence", v: "a consistent cadence you never have to maintain" },
      { k: "On-brand", v: "content matched to your voice and each platform" },
      { k: "Visibility", v: "a monthly report so you see what is working" },
    ],
    examples:
      "A med-spa gets three feed posts and daily stories a week, all designed and scheduled. A trading-education brand gets short clips repurposed from its long videos, posted across Instagram and TikTok.",
  },
  both: {
    title: "Both, together",
    tagline: "Email and social, run as one coordinated effort.",
    what:
      "Everything in Email marketing and Social media management, coordinated so your outbound and your brand presence reinforce each other.",
    how: [
      "We run both pipelines for you under one team.",
      "Cold email brings in warm leads while social keeps your brand visible and credible.",
      "Prospects who look you up after an email find an active, professional presence, which lifts reply and close rates.",
      "You get one point of contact and one combined report.",
    ],
    results: [
      { k: "Two channels", v: "outbound and presence, handled by one team" },
      { k: "Compounding", v: "social makes the email outreach more credible" },
      { k: "One report", v: "both channels in a single monthly view" },
    ],
    examples:
      "While email books seller appointments for a real-estate brand, its Instagram posts new listings and local market updates, so every prospect who checks the profile sees an active agent.",
  },
};

export default function Learn() {
  const { service } = useParams();
  const nav = useNavigate();
  const e = service ? EXPLAIN[service] : undefined;

  if (!e) {
    return (
      <div className="card">
        <h2>Not found</h2>
        <p className="sub">No explanation for that service.</p>
        <Link to="/" className="btn ghost" style={{ display: "inline-block" }}>Back to start</Link>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>{e.title}</h2>
      <p className="sub">{e.tagline}</p>
      <p style={{ color: "var(--text2)", lineHeight: 1.65 }}>{e.what}</p>

      <div className="learn-sec">
        <h3>How it works</h3>
        <ol className="learn-steps">
          {e.how.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      </div>

      <div className="learn-sec">
        <h3>What you can expect</h3>
        <div className="learn-result">
          {e.results.map((r, i) => (
            <div key={i} className="chip"><b>{r.k}</b>{r.v}</div>
          ))}
        </div>
      </div>

      <div className="learn-sec">
        <h3>Examples</h3>
        <div className="learn-ex">{e.examples}</div>
      </div>

      <button className="btn block" onClick={() => nav("/?svc=" + service)}>
        Choose this &amp; continue
      </button>
      <Link to="/" className="hint" style={{ display: "block", textAlign: "center", marginTop: 10 }}>
        &larr; Back to all options
      </Link>
    </div>
  );
}
