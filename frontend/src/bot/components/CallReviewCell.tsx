import { useStore } from "../store";
import type { CallRecord, CallReview } from "../types";
import { Icon } from "../lib/ui";
import ReviewBox from "./ReviewBox";
import { mmss, callTime } from "./CallList";
import { fullDate } from "../lib/ui";

const stop = (e: React.SyntheticEvent) => e.stopPropagation();

/** Mirrors CALL_REVIEW_MIN_SECONDS on the server: below this a call is a
 * ring-out with no conversation in it. */
const MIN_SECONDS = 20;
const isReviewable = (c: CallRecord) =>
  c.answered && c.recording_status === "stored" && (c.duration_seconds ?? 0) >= MIN_SECONDS;

/** Green / amber / red by score, so a bad call is visible without reading. */
const tone = (p: number) =>
  p >= 80 ? { color: "#16a34a", bg: "#16a34a22" }
    : p >= 60 ? { color: "#d97706", bg: "#d9770622" }
      : { color: "#dc2626", bg: "#dc262622" };

const SKIP_LABEL: Record<string, string> = {
  "not answered": "not answered",
  "no recording": "no recording",
  "could not transcribe": "could not be transcribed",
  "no speech detected": "no speech",
};

function Detail({ review, calls }: { review: CallReview; calls: CallRecord[] }) {
  const byId = new Map(calls.map((c) => [c.id, c]));
  const when = (id: string) => {
    const c = byId.get(id);
    return c ? fullDate(callTime(c)) : "";   // fullDate already includes the time
  };
  return (
    <div className="space-y-3 text-[12.5px] leading-relaxed">
      {review.combined_review && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Across all calls</div>
          <p className="whitespace-pre-wrap text-ink">{review.combined_review}</p>
        </div>
      )}
      {review.agent_missed.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Never done on any call</div>
          <ul className="space-y-1">
            {review.agent_missed.map((m, i) => (
              <li key={i} className="flex gap-1.5 text-muted"><span className="text-red-500">•</span><span>{m}</span></li>
            ))}
          </ul>
        </div>
      )}
      {review.per_call.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Call by call</div>
          <div className="divide-y divide-line/60">
            {review.per_call.map((p, i) => {
              const t = tone(p.percent);
              const c = byId.get(p.call_id);
              return (
                <div key={p.call_id} className="py-2">
                  <div className="mb-0.5 flex items-center gap-2">
                    <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold tabular-nums" style={{ color: t.color, background: t.bg }}>{p.percent}%</span>
                    <span className="text-[11px] text-muted">
                      {when(p.call_id) || `Call ${i + 1}`}{c ? ` · ${c.direction} · ${mmss(c.duration_seconds)}` : ""}
                    </span>
                  </div>
                  <p className="text-muted">{p.review}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {review.skipped.length > 0 && (
        <div className="border-t border-line/60 pt-2 text-[11.5px] text-muted">
          {review.skipped.length} call{review.skipped.length === 1 ? "" : "s"} not reviewed
          {" — "}
          {[...new Set(review.skipped.map((s) => SKIP_LABEL[s.reason] ?? s.reason))].join(", ")}
        </div>
      )}
      <div className="border-t border-line/60 pt-2 text-[11px] text-muted">Written by AI. Read-only.</div>
    </div>
  );
}

/**
 * The Call review cell: a button when the patient has never been reviewed, a
 * spinner while the worker runs, otherwise a colour-coded percentage that opens
 * the full review. Replaces the Agent and Via columns.
 */
export default function CallReviewCell({ phone, calls }: { phone: string; calls: CallRecord[] }) {
  const { callReviews, startCallReview } = useStore();
  const review = callReviews[phone];
  const status = review?.status;
  const reviewable = calls.filter(isReviewable).length;

  // Nothing to review and nothing reviewed before: offering the button would
  // spend a press to be told there was no conversation in any of these calls.
  if (!review && reviewable === 0) {
    return <span className="text-[12px] text-muted/60" title={`No answered recording over ${MIN_SECONDS}s`}>—</span>;
  }

  if (status === "queued" || status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
        <Icon name="refresh" size={12} className="animate-spin" />
        {status === "queued" ? "Queued…" : "Reviewing…"}
      </span>
    );
  }

  const run = (e: React.SyntheticEvent) => { stop(e); startCallReview(phone); };

  if (status === "failed") {
    return (
      <button onClick={run} onMouseDown={stop} title={review?.error ?? "Review failed"}
        className="inline-flex items-center gap-1 rounded-md bg-red-500/10 px-2 py-0.5 text-[12px] font-medium text-red-500 hover:bg-red-500/20">
        <Icon name="refresh" size={11} /> Retry
      </button>
    );
  }

  // Reviewed, but every call was skipped — say so instead of showing 0%.
  if (status === "done" && review && review.percent === null) {
    return <span className="text-[12px] text-muted/70" title={review.skipped.map((s) => s.reason).join(", ")}>—</span>;
  }

  if (status === "done" && review) {
    const t = tone(review.percent ?? 0);
    // Calls that arrived after the review ran: offer a refresh rather than
    // silently showing a score that no longer covers everything.
    const covered = new Set(review.calls_covered);
    const fresh = calls.filter((c) => isReviewable(c) && !covered.has(c.id)).length;
    return (
      <div className="flex items-center gap-1.5">
        <ReviewBox
          label="Call review"
          trigger={(open, ref) => (
            <button ref={ref} onClick={(e) => { stop(e); open(); }} onMouseDown={stop} title="Read the AI review"
              className="rounded-md px-2 py-0.5 text-[12.5px] font-semibold tabular-nums transition-opacity hover:opacity-80"
              style={{ color: t.color, background: t.bg }}>
              {review.percent}%
            </button>
          )}
        >
          <Detail review={review} calls={calls} />
        </ReviewBox>
        {fresh > 0 && (
          <button onClick={run} onMouseDown={stop} title={`${fresh} newer call${fresh === 1 ? "" : "s"} — run again`}
            className="grid h-5 w-5 place-items-center rounded text-muted hover:text-accent">
            <Icon name="refresh" size={11} />
          </button>
        )}
      </div>
    );
  }

  return (
    <button onClick={run} onMouseDown={stop} title="Review this patient's calls with AI"
      className="inline-flex items-center gap-1 rounded-md bg-accent/15 px-2 py-0.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/25">
      <Icon name="sparkle" size={11} /> Review
    </button>
  );
}
