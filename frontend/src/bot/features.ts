/**
 * Feature flags — which parts of the CRM a client is allowed to see.
 *
 * The inbox itself is never a flag: it is the product. Everything else can be
 * switched off per client so a tenant only ever sees what we have decided to
 * expose to them.
 *
 * What a client gets = DEFAULTS, overlaid with `features` on the client document
 * from GET /auth/me (Ripplica's grant — authoritative), then the clinic's own
 * `feature_prefs` (Settings → Features; stored on the client, so every device
 * agrees). A preference can only hide something that was granted.
 *
 * On top of that, a local override (localStorage "crm.features", or ?ff= in the
 * URL) can switch things OFF for previewing — never on.
 *
 * The query form takes a comma list, `-` prefix turns a flag off:
 *   ?ff=-campaigns,-templates      hide campaigns and templates
 *   ?ff=only:leads                 inbox + leads only
 *   ?ff=all                        drop local overrides
 * A query override is also written to localStorage so it survives a reload.
 */

export const FEATURE_KEYS = [
  "leads",
  "campaigns",
  "templates",
  "contacts",
  "notes",
  "voiceNotes",
  "disposition",
  "customColumns",
  "calls",
  "callReview",
] as const;

export type Feature = (typeof FEATURE_KEYS)[number];
export type Features = Record<Feature, boolean>;

/** Human labels, for the settings screen. */
export const FEATURE_LABELS: Record<Feature, string> = {
  leads: "Leads table",
  campaigns: "Broadcasts (bulk template sends)",
  templates: "Templates",
  contacts: "Contacts",
  notes: "Internal notes on chats",
  voiceNotes: "Send voice notes",
  disposition: "Disposition and remarks",
  customColumns: "Custom lead columns",
  calls: "Calls (FasterQ recordings)",
  callReview: "AI call review",
};

const DEFAULTS: Features = {
  leads: true,
  campaigns: true,
  templates: true,
  contacts: true,
  notes: true,
  voiceNotes: true,
  disposition: true,
  customColumns: true,
  calls: true,
  // Not granted by default: a press spends money on transcription + review, so
  // Ripplica turns this on per clinic (PATCH /admin/clients/{id}/features).
  callReview: false,
};

/** What a clinic sees before it touches Settings: everything granted, except notes. */
// callReview is on HERE but off in DEFAULTS: the Ripplica grant is the gate, so
// once it is granted the clinic sees it without having to find a second toggle.
// (notes/calls are the opposite shape: granted to everyone, opted into per clinic.)
export const PREF_DEFAULTS: Features = { ...DEFAULTS, notes: false, calls: false, callReview: true };

const LS_KEY = "crm.features";
const isFeature = (k: string): k is Feature => (FEATURE_KEYS as readonly string[]).includes(k);

/** Keep only known keys, coerce to boolean. */
export function clean(raw: unknown): Partial<Features> {
  const out: Partial<Features> = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (isFeature(k)) out[k] = !!v;
  }
  return out;
}

function fromStorage(): Partial<Features> {
  try { return clean(JSON.parse(localStorage.getItem(LS_KEY) || "null")); } catch { return {}; }
}

/** `?ff=-campaigns,-templates` / `?ff=only:leads,contacts` / `?ff=all` */
function fromQuery(): Partial<Features> | "clear" | null {
  let spec: string | null = null;
  try { spec = new URLSearchParams(window.location.search).get("ff"); } catch { return null; }
  if (spec === null) return null;
  const parts = spec.split(",").map((s) => s.trim()).filter(Boolean);
  if (!parts.length) return null;

  if (parts[0] === "all") return "clear";

  const only = parts[0].startsWith("only:");
  if (only) {
    const keep = new Set([parts[0].slice(5), ...parts.slice(1)].filter(isFeature));
    return Object.fromEntries(FEATURE_KEYS.map((k) => [k, keep.has(k)])) as Features;
  }
  const out: Partial<Features> = {};
  for (const p of parts) {
    const off = p.startsWith("-");
    const key = off ? p.slice(1) : p;
    if (isFeature(key)) out[key] = !off;
  }
  return out;
}

/**
 * Current flags. Pass the `features` object from the client document to fold the
 * server's decision in; call again whenever that arrives.
 *
 * The server is authoritative. A local or query override can only ever turn a
 * feature OFF, never on — so nobody can reveal something we did not grant them.
 */
export function resolveFeatures(fromClient?: unknown, prefs?: unknown): Features {
  const query = fromQuery();
  if (query === "clear") {
    clearFeatureOverride();
  } else if (query) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(query)); } catch { /* private mode */ }
  }
  const granted = grantedFeatures(fromClient);
  const chosen: Features = { ...PREF_DEFAULTS, ...clean(prefs) };
  const override = { ...fromStorage(), ...(query && query !== "clear" ? query : {}) };
  const out: Features = { ...granted };
  for (const k of FEATURE_KEYS) {
    if (!chosen[k]) out[k] = false;
    if (k in override && !override[k]) out[k] = false;
  }
  return out;
}

/** Ripplica's grant alone — what the Settings screen may offer the clinic. */
export function grantedFeatures(fromClient?: unknown): Features {
  return { ...DEFAULTS, ...clean(fromClient) };
}

/** The local override as stored (settings screen reads this). */
export function readFeatureOverride(): Partial<Features> {
  return fromStorage();
}

/** Persist a local override (used by the settings screen). */
export function saveFeatureOverride(next: Partial<Features>): void {
  try { localStorage.setItem(LS_KEY, JSON.stringify(clean(next))); } catch { /* private mode */ }
}

export function clearFeatureOverride(): void {
  try { localStorage.removeItem(LS_KEY); } catch { /* private mode */ }
}
