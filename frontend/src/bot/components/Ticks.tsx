import type { MessageStatus } from "../types";

/**
 * Delivery-state glyphs, drawn from the supplied artwork.
 *
 * Colour policy: the source files for sent, delivered and pending are pure
 * black, which disappears on the dark palette, so those draw in `currentColor`
 * and inherit the muted text colour. Read and failed carry meaning in their
 * colour, so they use per-theme values (--tick-read / --tick-warn in index.css)
 * instead of the single literal colour baked into the asset — the supplied blue
 * is ~1.3:1 against the dark outgoing bubble, i.e. invisible.
 */

const SINGLE = "M4.4 13.3 L9 16.9 L19.5 7.3";
// The double mark is the same tick repeated at -3 and +3 on x, as measured off
// the source art; drawn in one colour the pair merges exactly like the original.
const DOUBLE_L = "M1.4 13.3 L6 16.9 L16.5 7.3";
const DOUBLE_R = "M7.4 13.3 L12 16.9 L22.5 7.3";

const SIZE = 14;

function Marks({ children }: { children: React.ReactNode }) {
  return (
    <svg width={SIZE} height={SIZE} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="butt" strokeLinejoin="miter" aria-hidden>
      {children}
    </svg>
  );
}

export default function Ticks({ status, error }: { status: MessageStatus; error?: string }) {
  if (status === "failed")
    return (
      <span title={error ? `Failed: ${error}` : "Failed to send"} style={{ color: "var(--tick-warn)" }}>
        <svg width={SIZE} height={SIZE} viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M10.12 5.17 Q12 1.98 13.88 5.17 L20.02 15.63 Q21.92 18.85 18.18 18.85 L5.82 18.85 Q2.08 18.85 3.98 15.63 Z" />
          <path d="M12 7.9 L12 13.4" />
          <path d="M12 16.3 L12 16.35" />
        </svg>
      </span>
    );

  if (status === "created")
    return (
      <span title="Pending" className="text-muted">
        <Marks>
          <circle cx="11.97" cy="11.97" r="10" />
          <path d="M13.9 7.1 L12.05 10.6 L12.05 18.5" />
        </Marks>
      </span>
    );

  const read = status === "read";
  const double = read || status === "delivered";
  return (
    <span title={status} className={read ? undefined : "text-muted"}
          style={read ? { color: "var(--tick-read)" } : undefined}>
      <Marks>
        {double ? (<><path d={DOUBLE_L} /><path d={DOUBLE_R} /></>) : <path d={SINGLE} />}
      </Marks>
    </span>
  );
}
