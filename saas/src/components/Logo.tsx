// The AUREON GLOBAL logo — the exact gold-globe SVG + wordmark from aureonglobal.de,
// so the portal header/login match the website brand.

export default function Logo({ size = 40, showText = true }: { size?: number; showText?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
      <span style={{ width: size, height: size, display: "inline-block", flex: "0 0 auto" }}>
        <svg viewBox="0 0 100 100" width={size} height={size}
          style={{ filter: "drop-shadow(0 2px 10px rgba(212,175,55,0.4))" }}>
          <defs>
            <linearGradient id="aureonGlobe" x1="10%" y1="10%" x2="90%" y2="90%">
              <stop offset="5%" stopColor="#FFF8D6" />
              <stop offset="35%" stopColor="#E6C259" />
              <stop offset="65%" stopColor="#B68E2D" />
              <stop offset="95%" stopColor="#755615" />
            </linearGradient>
          </defs>
          <g fill="url(#aureonGlobe)">
            <ellipse cx="50" cy="15" rx="20" ry="7" />
            <path d="M 18 26 Q 50 33 82 26 L 82 34 Q 50 41 18 34 Z" />
            <path d="M 8 40 Q 50 47 92 40 L 92 49 Q 50 56 8 49 Z" />
            <path d="M 8 55 Q 50 62 92 55 L 92 64 Q 50 71 8 64 Z" />
            <path d="M 18 70 Q 50 77 82 70 L 82 78 Q 50 85 18 78 Z" />
            <path d="M 32 84 Q 50 89 68 84 L 68 89 Q 50 94 32 89 Z" />
          </g>
        </svg>
      </span>
      {showText && (
        <span style={{ display: "flex", flexDirection: "column", justifyContent: "center", lineHeight: 1 }}>
          <span style={{ fontWeight: 900, letterSpacing: ".02em", color: "#fff", fontSize: 18, marginBottom: 4 }}>
            AUREON GLOBAL
          </span>
          <span style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: ".3em", color: "var(--accent)", fontWeight: 700 }}>
            Quality Converts
          </span>
        </span>
      )}
    </span>
  );
}
