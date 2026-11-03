import type { Density, TemplateCategory, TemplateStatus } from "../types";

export const CATEGORY_COLOR: Record<TemplateCategory, string> = {
  MARKETING: "#3b82f6",
  UTILITY: "#22c55e",
  AUTHENTICATION: "#a855f7",
};

export const STATUS_COLOR: Record<TemplateStatus, string> = {
  APPROVED: "#22c55e",
  PENDING: "#f59e0b",
  REJECTED: "#ef4444",
};

export const STATUS_LABEL: Record<TemplateStatus, string> = {
  APPROVED: "Verified",
  PENDING: "In review",
  REJECTED: "Rejected",
};

/** Conversation/contact source badges: CTWA ad, organic WhatsApp, imported. */
export const SOURCE_COLOR: Record<string, string> = {
  ctwa: "#f59e0b",
  whatsapp: "#22c55e",
  inbound: "#22c55e",
  import: "#64748b",
};
export const SOURCE_LABEL: Record<string, string> = {
  ctwa: "CTWA ad",
  whatsapp: "WhatsApp",
  inbound: "WhatsApp",
  import: "Imported",
};

/** Server timestamps may lack a zone suffix; treat those as UTC (mirrors frontend/format.ts). */
export function utcMs(iso: string): number {
  const time = iso.slice(11);
  const hasZone = time.includes("Z") || time.includes("+") || time.includes("-");
  return new Date(hasZone ? iso : iso + "Z").getTime();
}
/** Every timestamp in the CRM is shown in India time, whatever the viewer's device zone. */
export const TZ = "Asia/Kolkata";
const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-IN", { timeZone: TZ, ...opts }).format(new Date(utcMs(iso)));
export function fullDate(iso: string | null): string {
  if (!iso) return "—";
  return fmt(iso, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true });
}
/** "9:35 am" (IST) */
export function clockOnly(iso: string): string {
  return fmt(iso, { hour: "numeric", minute: "2-digit", hour12: true });
}
export function displayName(name: string | null | undefined, phone: string): string {
  return name?.trim() || `+${phone}`;
}
export function initials(name: string | null | undefined, phone: string): string {
  const n = name?.trim();
  if (!n) return phone.slice(-2);
  const parts = n.split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function hueFromString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}

/** color for an arbitrary enum value (dispositions, branches, …) */
export function enumColor(v: string): string {
  return `hsl(${hueFromString(v)} 55% 55%)`;
}

export const DENSITY: Record<Density, { pad: string; text: string }> = {
  compact: { pad: "py-1", text: "text-[12px]" },
  cozy: { pad: "py-1.5", text: "text-[12.5px]" },
  comfortable: { pad: "py-2.5", text: "text-[14px]" },
};

/** Mirrors the `md` variant in index.css: anything not wide AND tall enough is a
 *  phone, so a landscape handset never gets the desktop layout. */
export const MOBILE_QUERY = "(max-width: 47.999rem), (max-height: 31.999rem)";
export const isMobile = () => typeof window !== "undefined" && window.matchMedia(MOBILE_QUERY).matches;

export function Badge({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-[1px] text-[11px] font-medium whitespace-nowrap"
      style={{ color, background: color + "22" }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {children}
    </span>
  );
}

export function Avatar({ name, size = 26 }: { name: string; size?: number }) {
  const initials = name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span
      title={name}
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{ width: size, height: size, background: `hsl(${hueFromString(name)} 55% 50%)`, fontSize: size * 0.4 }}
    >
      {initials || "?"}
    </span>
  );
}

export function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - utcMs(iso)) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d`;
  return fmt(iso, { day: "numeric", month: "short", year: "numeric" });
}

/** "10 Sep, 9:35 am" (IST) */
export function clockTime(iso: string): string {
  return fmt(iso, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

/** IST calendar day as YYYY-MM-DD, for grouping by day */
const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
export function dayKey(iso: string): string {
  return dayKeyFmt.format(new Date(utcMs(iso)));
}

/** Chat-list stamp, WhatsApp style: time today, "Yesterday", else a short date. */
export function listTime(iso: string | null): string {
  if (!iso) return "";
  const key = dayKey(iso);
  const now = new Date();
  if (key === dayKey(now.toISOString())) return clockOnly(iso);
  if (key === dayKey(new Date(now.getTime() - 86400000).toISOString())) return "Yesterday";
  return fmt(iso, { day: "numeric", month: "short" });
}

/** human day header: Today / Yesterday / "Mon, 1 Sep" */
export function dayLabel(iso: string): string {
  const key = dayKey(iso);
  const now = new Date();
  const today = dayKey(now.toISOString());
  const yest = dayKey(new Date(now.getTime() - 86400000).toISOString());
  if (key === today) return "Today";
  if (key === yest) return "Yesterday";
  return fmt(iso, { weekday: "short", day: "numeric", month: "short" });
}

const PATHS: Record<string, string> = {
  table: "M3 5h18v14H3zM3 10h18M9 5v14",
  kanban: "M4 4h4v12H4zM10 4h4v8h-4zM16 4h4v16h-4z",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6L5.5 5Z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
  sun: "M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  phone: "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.6A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z",
  calendar: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  chevron: "m9 18 6-6-6-6",
  chevronDown: "m6 9 6 6 6-6",
  plus: "M12 5v14M5 12h14",
  user: "M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  back: "m15 18-6-6 6-6",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z",
  doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M8 13h8M8 17h6",
  users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  mic: "M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3ZM19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8",
  more: "M12 5h.01M12 12h.01M12 19h.01",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0",
  bellOff: "M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5M17 17H3s3-2 3-9a4.7 4.7 0 0 1 .3-1.7M10.3 21a1.94 1.94 0 0 0 3.4 0M2 2l20 20",
  // An angled bullhorn: horn, handle, sound lines. The previous path under this
  // name was a speaker cone with arcs, which reads as a volume control.
  megaphone: "M3.6 14.2 13.4 4.6l5.2 9-13 3.4zM6.6 17.2 8.8 21a1 1 0 0 0 1.4.2l1-.7M19 6.6 20.6 4.4M21 9.4 23 8.6M21.2 12.4h2.2",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 16v-4M12 8h.01",
  tag: "M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8ZM7 7h.01",
  stop: "M5 5h14v14H5z",
  play: "M6 4v16l14-8z",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z",
  refresh: "M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15",
};

export function Icon({ name, size = 16, className = "" }: { name: keyof typeof PATHS; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  );
}
