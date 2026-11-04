import type {
  Conversation, MessageRecord, MessageStatus, Note, Contact, Template, Broadcast, BroadcastRecipient,
  WorkflowRun, NodeResponse, CrmFields, WhatsAppAccount, ClientSettings, AiUsage, Disposition,
  StatusHistoryEntry, CallRecord,
} from "../types";
import { ACTIVE_FLOW } from "./flows";
import { renderTemplateBody, countBodyVariables } from "../lib/templates";

export interface DB {
  conversations: Conversation[];
  messages: Record<string, MessageRecord[]>;
  notes: Record<string, Note[]>;
  crm: Record<string, CrmFields>;
  contacts: Contact[];
  templates: Template[];
  broadcasts: Broadcast[];
  recipients: Record<string, BroadcastRecipient[]>;
  runs: WorkflowRun[];
  /** FasterQ calls (remote only; the demo has none) */
  calls?: CallRecord[];
  nodeResponses: Record<string, NodeResponse[]>;
  account: WhatsAppAccount;
  client: ClientSettings;
  usage: AiUsage;
}

export const ACCOUNT_ID = "wa:b2f9485cad";
export const WABA_ID = "2022582488496037";

// ---- deterministic rng ----
function rng(seed: number) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0), s / 0xffffffff); }
const rand = rng(20260910);
const pick = <T,>(a: T[]) => a[Math.floor(rand() * a.length)];
const chance = (p: number) => rand() < p;
let counter = 0;
const uid = (p: string) => `${p}:${(++counter).toString(36).padStart(4, "0")}${Math.floor(rand() * 1e6).toString(36)}`;
const agoMs = (ms: number) => new Date(Date.now() - ms).toISOString();
const H = 3600_000, M = 60_000;

const NAMES = [
  "Ramesh Gupta", "Sunita Devi", "Md Arif Ilyas", "Kavita Joshi", "Deepak Rao", "Neha Kapoor", "Arjun Mehta",
  "Pooja Bansal", "Sanjay Yadav", "Farha Khan", "Harpreet Kaur", "Mohan Lal", "Ritu Aggarwal", "Imran Sheikh",
  "Geeta Prasad", "Naveen Chawla", "Shreya Iyer", "Balwinder Singh", "Ayesha Siddiqui", "Rohit Malhotra",
  "Lakshmi Menon", "Tarun Bhatia", "Nisha Reddy", "Karan Ahuja", "Meena Kumari", "Suresh Pillai", "Divya Shetty",
];
const PAINS = ["Low back pain / sciatica", "Knee pain", "Neck pain & headache", "Shoulder pain", "Cancer pain", "Hip / buttock pain", "Facial pain", "Ankle / heel pain"];
const DOCTORS = ["Dr. Ashu Kumar Jain", "Dr. Tariq", "Dr. Kamal Aggarwal", "Dr. Ankit Chawla"];
const CAMPAIGNS = ["Advanced Pain Care Q3", "Knee Relief", "Back Pain Awareness"];
const HEADLINES = ["Knee pain? Book a consult today", "Advanced back pain treatment in Gurugram", "Say goodbye to sciatica"];
const DISPOSITIONS: (Disposition | "")[] = ["DID_NOT_CONNECT", "FOLLOW_UP_REQUIRED", "INTERESTED", "APPOINTMENT_REQUESTED", "NOT_INTERESTED", "Repeated", "", ""];

// ---- tiny real assets so media actually renders/plays ----
/** A short WAV tone as a data URI (playable in <audio>). */
function toneWav(seconds = 3, freq = 440): string {
  const rate = 8000, n = Math.floor(rate * seconds);
  const buf = new ArrayBuffer(44 + n);
  const v = new DataView(buf);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true);
  str(36, "data"); v.setUint32(40, n, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate, env = Math.min(1, t * 8) * Math.max(0, 1 - t / seconds);
    const f = freq * (1 + 0.15 * Math.sin(t * 3));
    v.setUint8(44 + i, 128 + Math.round(90 * env * Math.sin(2 * Math.PI * f * t)));
  }
  let bin = ""; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return "data:audio/wav;base64," + btoa(bin);
}
/** An SVG "photo" (e.g. an MRI report) as a data URI. */
function svgImage(label: string, hue: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 60% 30%)"/><stop offset="1" stop-color="hsl(${hue + 40} 60% 15%)"/></linearGradient></defs><rect width="640" height="480" fill="url(#g)"/><circle cx="320" cy="220" r="120" fill="none" stroke="white" stroke-opacity=".35" stroke-width="18"/><text x="320" y="420" font-family="sans-serif" font-size="28" fill="white" fill-opacity=".85" text-anchor="middle">${label}</text></svg>`;
  // Percent-encode (not btoa): labels contain non-Latin-1 characters.
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}
const VOICE_SRC = toneWav(4, 330);
const IMG_MRI = svgImage("MRI report — L4/L5", 210);
const IMG_XRAY = svgImage("Knee X-Ray (AP view)", 140);

function history(status: MessageStatus, at: number): StatusHistoryEntry[] {
  const ladder: MessageStatus[] = ["sent", "delivered", "read"];
  const upto = status === "failed" ? [] : ladder.slice(0, ladder.indexOf(status) + 1);
  return upto.map((s, i) => ({ status: s, received_at: new Date(at + i * 900).toISOString(), previous_status: i ? ladder[i - 1] : "created" }));
}

// ---- builders ----
type Msg = Partial<MessageRecord> & { direction: "incoming" | "outgoing"; message_type?: MessageRecord["message_type"]; text?: string | null };
function msg(convPhone: string, at: number, m: Msg): MessageRecord {
  const out = m.direction === "outgoing";
  const status: MessageStatus = m.status ?? (out ? pick<MessageStatus>(["delivered", "read", "read", "sent"]) : "read");
  const wamid = `wamid.${uid("m").replace(/[^a-z0-9]/gi, "").toUpperCase()}`;
  return {
    id: uid("msg"),
    whatsapp_account_id: ACCOUNT_ID,
    contact_phone: convPhone,
    direction: m.direction,
    message_type: m.message_type ?? "text",
    text: m.text ?? null,
    metadata: { meta_message_id: wamid, ...(out ? { status_history: history(status, at) } : {}), ...(m.metadata ?? {}) },
    status,
    created_at: new Date(at).toISOString(),
  };
}

const QUESTIONS: Record<string, string> = {
  pain: "What pain or problem are you facing?", appt_type: "How would you like to consult?",
  appt_date: "Which date works for you?", appt_time: "Preferred time?", consult_mode: "Consult mode?",
  branch: "Which branch is convenient?", doctor: "Any doctor preference?",
};

export function makeSeed(): DB {
  const conversations: Conversation[] = [];
  const messages: Record<string, MessageRecord[]> = {};
  const notes: Record<string, Note[]> = {};
  const crm: Record<string, CrmFields> = {};
  const runs: WorkflowRun[] = [];
  const nodeResponses: Record<string, NodeResponse[]> = {};
  const contacts: Contact[] = [];

  // Scenario matrix: each entry = a conversation state we want visible.
  type Scenario = { status: Conversation["status"]; paused?: boolean; inboundAgo: number; resolvedBy?: "agent" | "auto"; ctwa?: boolean; kind: "bot" | "agent" | "ai" | "template" | "timeout" | "media" | "failed" };
  const scenarios: Scenario[] = [
    { status: "open", inboundAgo: 12 * M, kind: "bot", ctwa: true },
    { status: "open", inboundAgo: 40 * M, kind: "agent", paused: true },
    { status: "open", inboundAgo: 2 * H, kind: "ai" },
    { status: "open", inboundAgo: 23 * H + 15 * M, kind: "bot" },            // <1h left → countdown
    { status: "open", inboundAgo: 5 * H, kind: "media", ctwa: true },
    { status: "open", inboundAgo: 1 * H, kind: "agent", paused: true },
    { status: "open", inboundAgo: 3 * H, kind: "failed" },
    { status: "open", inboundAgo: 6 * H, kind: "template" },
    { status: "resolved", inboundAgo: 4 * H, kind: "agent", resolvedBy: "agent" },
    { status: "resolved", inboundAgo: 9 * H, kind: "timeout", resolvedBy: "auto" },
    { status: "resolved", inboundAgo: 7 * H, kind: "bot", resolvedBy: "agent", ctwa: true },
    { status: "expired", inboundAgo: 30 * H, kind: "bot" },
    { status: "expired", inboundAgo: 2 * 24 * H, kind: "ai", ctwa: true },
    { status: "expired", inboundAgo: 3 * 24 * H, kind: "template" },
    { status: "open", inboundAgo: 20 * M, kind: "bot" },
    { status: "open", inboundAgo: 8 * H, kind: "media" },
    { status: "expired", inboundAgo: 5 * 24 * H, kind: "bot" },
    { status: "resolved", inboundAgo: 11 * H, kind: "ai", resolvedBy: "auto" },
  ];

  const usedNames = new Set<string>();
  scenarios.forEach((sc, i) => {
    let name = pick(NAMES); while (usedNames.has(name)) name = pick(NAMES); usedNames.add(name);
    const first = name.split(" ")[0];
    const phone = "9198" + Math.floor(10000000 + rand() * 89999999).toString().slice(0, 8);
    const convId = uid("conv");
    const lastInbound = Date.now() - sc.inboundAgo;
    const start = lastInbound - (20 + Math.floor(rand() * 90)) * M;
    let t = start;
    const step = () => (t += (1 + rand() * 4) * M);
    const ms: MessageRecord[] = [];
    const push = (m: Msg) => ms.push(msg(phone, step(), m));

    // opening
    push({ direction: "incoming", text: sc.ctwa ? "Hi, I saw your ad about knee pain treatment." : "Hi, I'd like to book an appointment." });
    push({ direction: "outgoing", text: `Welcome to Jain Pain Clinic, ${first}! 🙏 Please choose your language.`, message_type: "interactive_buttons", metadata: { options: [{ id: "en", label: "English" }, { id: "hi", label: "हिन्दी" }] } });
    push({ direction: "incoming", text: "English", metadata: { reply_title: "English" } });
    push({ direction: "outgoing", text: "What pain or problem are you facing?", message_type: "interactive_list", metadata: { list_config: { button_text: "Choose", sections: [{ title: "Common complaints", rows: PAINS.slice(0, 5).map((p) => ({ id: p, label: p })) }, { title: "Other", rows: [{ id: "other", label: "Something else" }] }] } } });
    const pain = pick(PAINS);
    push({ direction: "incoming", text: pain, metadata: { reply_title: pain } });

    if (sc.kind === "media") {
      push({ direction: "outgoing", text: "Could you share your latest MRI / X-ray report?" });
      push({ direction: "incoming", text: null, message_type: "image", metadata: { media: { type: "image", mime_type: "image/svg+xml", filename: i % 2 ? "knee_xray.png" : "mri_report.png", caption: i % 2 ? "Knee X-ray from Tuesday" : "My MRI from last month", src: i % 2 ? IMG_XRAY : IMG_MRI } } });
      push({ direction: "incoming", text: null, message_type: "document", metadata: { media: { type: "document", mime_type: "application/pdf", filename: "prescription_aug.pdf", src: "#" } } });
      push({ direction: "incoming", text: null, message_type: "audio", metadata: { media: { type: "audio", mime_type: "audio/wav", voice: true, duration: 4, src: VOICE_SRC } } });
      push({ direction: "outgoing", text: "Thanks! Dr. Jain will review these before your visit." });
    }
    if (sc.kind === "ai") {
      push({ direction: "outgoing", text: `समझ गया—आपको ${pain.toLowerCase()} है। आप आज क्या करना चाहते हैं?` });
      push({ direction: "incoming", text: "I want to book for Saturday morning" });
      push({ direction: "outgoing", text: "Sure. Which branch is convenient — Gurugram, New Delhi or Faridabad?", message_type: "interactive_buttons", metadata: { options: [{ label: "Gurugram" }, { label: "New Delhi" }, { label: "Faridabad" }] } });
      push({ direction: "incoming", text: "Gurugram", metadata: { reply_title: "Gurugram" } });
      // quoted reply
      const q = ms[ms.length - 2];
      push({ direction: "incoming", text: "Actually can I do Sunday instead?", metadata: { reply_to_wamid: q.metadata.meta_message_id } });
    }
    if (sc.kind === "agent") {
      push({ direction: "incoming", text: "Can I speak to a person please?" });
      push({ direction: "outgoing", text: `Hi ${first}, this is Priya from the clinic. I'll help you with the booking. Which day suits you?`, metadata: { sent_by: "agent" } });
      push({ direction: "incoming", text: "Thursday after 5pm" });
      push({ direction: "outgoing", text: "Booked for Thursday 5:30 PM with Dr. Jain, Gurugram. You'll get a confirmation shortly. 🙂", metadata: { sent_by: "agent" }, status: "read" });
    }
    if (sc.kind === "template") {
      push({ direction: "outgoing", text: `Hi ${first}, thank you for visiting Jain Pain Clinic on 5 September. We'd love your feedback — how was your experience?`, message_type: "template", metadata: { sent_by: "template", template: { name: "appointment_feedback", language: "en", params: [first, "5 September"] } }, status: "delivered" });
    }
    if (sc.kind === "timeout") {
      push({ direction: "outgoing", text: "Your chat was closed due to inactivity. Our team will call you back soon. Send us a message anytime to start over. 🙏", metadata: { sent_by: "inactivity_timeout" }, status: "delivered" });
    }
    if (sc.kind === "failed") {
      push({ direction: "outgoing", text: "Please confirm your appointment for tomorrow 11 AM.", status: "failed", metadata: { send_error: "Outside the 24-hour customer service window (131047)" } });
    }
    if (sc.kind === "bot" && !sc.ctwa) {
      push({ direction: "outgoing", text: "Great. Would you prefer a clinic visit or an online consultation?", message_type: "interactive_buttons", metadata: { options: [{ label: "Clinic visit" }, { label: "Online consultation" }] } });
      push({ direction: "incoming", text: "Clinic visit", metadata: { reply_title: "Clinic visit" } });
    }
    // make sure the last inbound lands exactly at lastInbound
    const lastIn = [...ms].reverse().find((m) => m.direction === "incoming");
    if (lastIn) lastIn.created_at = new Date(lastInbound).toISOString();
    const lastAny = ms[ms.length - 1];
    const lastAt = Math.max(new Date(lastAny.created_at).getTime(), lastInbound);

    const preview = (m: MessageRecord) => m.message_type === "template" ? `📋 ${m.metadata.template?.name}` : m.message_type === "image" ? "📷 Photo" : m.message_type === "audio" ? "🎤 Voice message" : m.message_type === "document" ? `📄 ${m.metadata.media?.filename}` : (m.metadata.reply_title ?? m.text ?? "");

    const conv: Conversation = {
      id: convId, whatsapp_account_id: ACCOUNT_ID, contact_phone: phone, contact_name: name,
      status: sc.status, bot_paused: !!sc.paused && sc.status === "open", awaiting_template_reply: false, tags: chance(0.35) ? [pick(["urgent", "vip", "follow-up", "re-book"])] : [], attributes: {},
      source: sc.ctwa ? "ctwa" : "whatsapp",
      source_id: sc.ctwa ? "1205" + Math.floor(rand() * 1e9) : null,
      source_url: sc.ctwa ? "https://fb.me/2xk9ad" + Math.floor(rand() * 999) : null,
      ctwa_clid: sc.ctwa ? "AfXxq" + uid("c").slice(2) : null,
      source_type: sc.ctwa ? "ad" : null,
      headline: sc.ctwa ? pick(HEADLINES) : null,
      last_message_text: preview(lastAny), last_message_at: new Date(lastAt).toISOString(),
      last_message_direction: lastAny.direction, last_inbound_at: new Date(lastInbound).toISOString(),
      unread_count: sc.status === "open" && lastAny.direction === "incoming" ? 1 + Math.floor(rand() * 3) : 0,
      resolved_at: sc.status === "resolved" ? new Date(lastAt + 5 * M).toISOString() : null,
      resolved_by: sc.status === "resolved" ? (sc.resolvedBy ?? "agent") : null,
      created_at: new Date(start).toISOString(),
      active_workflow_run_id: null,
    };
    conversations.push(conv);
    messages[convId] = ms;
    crm[convId] = {
      disposition: pick(DISPOSITIONS),
      call_tried: chance(0.5) ? 1 + Math.floor(rand() * 3) : 0,
      remark: chance(0.35) ? pick(["Wants a morning slot", "Asked about fee\nWill confirm tomorrow", "Referred by Dr. Tariq — VIP", "Not picking up, try after 6pm"]) : "",
      custom: {},
    };
    if (chance(0.3)) notes[convId] = [{ id: uid("note"), conversation_id: convId, text: pick(["Patient prefers Hindi. Call after 6pm.", "Asked for fee details — shared ₹800 consult.", "VIP — referred by Dr. Tariq."]), at: new Date(lastAt - 3 * M).toISOString() }];

    // run (lead record)
    const booked = sc.status === "resolved" || chance(0.4);
    const vars: Record<string, string> = { pain };
    if (booked) { vars.appt_type = pick(ACTIVE_FLOW.fields[1].options!); vars.appt_date = `${10 + Math.floor(rand() * 18)} Sep 2026`; vars.appt_time = pick(["10:30 AM", "12:00 PM", "5:30 PM"]); vars.doctor = pick(DOCTORS); }
    vars.branch = pick(["Gurugram", "New Delhi", "Faridabad"]);
    if (sc.ctwa) { vars.campaign = pick(CAMPAIGNS); vars.ad_id = conv.source_id!; }
    const runId = uid("run");
    const runStatus: WorkflowRun["status"] = sc.status === "resolved" ? "completed" : sc.status === "expired" ? "cancelled" : sc.paused ? "cancelled" : "waiting_for_user";
    const pushOutcome = sc.status === "resolved" || sc.status === "expired";
    runs.push({
      id: runId, whatsapp_account_id: ACCOUNT_ID, workflow_id: "wf:jpc", contact_phone: phone, status: runStatus, variables: vars,
      crm_pushed_at: pushOutcome && chance(0.8) ? new Date(lastAt + 2 * M).toISOString() : null,
      crm_push_result: pushOutcome ? (chance(0.8)
        ? { reason: sc.resolvedBy === "auto" ? "timeout" : "completed", status_code: 200, ok: true, terminal: true, attempts: 1, skipped_fields: booked ? [] : ["appt_date", "appt_time"], last_attempt_at: new Date(lastAt + 2 * M).toISOString() }
        : { reason: "timeout", status_code: 503, ok: false, terminal: false, attempts: 2, error: "service unavailable", last_attempt_at: new Date(lastAt + 2 * M).toISOString() }) : null,
      token_usage: sc.kind === "ai" ? { prompt_tokens: 11000 + Math.floor(rand() * 30000), completion_tokens: 900 + Math.floor(rand() * 3000), total_tokens: 0, cached_tokens: 6000 + Math.floor(rand() * 15000), turns: 4 + Math.floor(rand() * 10), cost_usd: 0 } : null,
      started_at: conv.created_at, completed_at: runStatus === "completed" ? conv.resolved_at : null,
    });
    const tu = runs[runs.length - 1].token_usage;
    if (tu) { tu.total_tokens = tu.prompt_tokens + tu.completion_tokens; tu.cost_usd = +(((tu.prompt_tokens - tu.cached_tokens) / 1e6) * 0.2 + (tu.cached_tokens / 1e6) * 0.02 + (tu.completion_tokens / 1e6) * 1.2).toFixed(6); }
    nodeResponses[runId] = Object.entries(vars).filter(([k]) => QUESTIONS[k]).map(([k, v], j) => ({ id: uid("nr"), workflow_run_id: runId, variable_name: k, question: QUESTIONS[k], response: v, at: new Date(start + (j + 1) * 3 * M).toISOString() }));
    conv.active_workflow_run_id = runStatus === "waiting_for_user" ? runId : null;

    contacts.push({ id: uid("ct"), whatsapp_account_id: ACCOUNT_ID, phone, name, source: sc.ctwa ? "ctwa" : "inbound", opted_out: false, marketing_opt_in: true, tags: conv.tags, last_inbound_at: conv.last_inbound_at, created_at: conv.created_at });
    void i;
  });

  // imported contacts (no conversation yet) + one opted-out
  ["Vikas Nanda", "Preeti Sharma", "Anand Kumar", "Ruchi Verma"].forEach((n, j) => {
    contacts.push({ id: uid("ct"), whatsapp_account_id: ACCOUNT_ID, phone: "9197" + (10000000 + j * 3131 + Math.floor(rand() * 8000000)).toString().slice(0, 8), name: n, source: "import", opted_out: j === 3, marketing_opt_in: j !== 3, tags: j < 2 ? ["camp-sep", "knee"] : ["camp-sep"], last_inbound_at: null, created_at: agoMs((3 + j) * 24 * H) });
  });

  // templates (real Meta component shapes)
  const T = (name: string, category: Template["category"], status: Template["status"], body: string, footer?: string, rejected?: string): Template => {
    const components: Template["components"] = [{ type: "BODY", text: body }];
    const n = countBodyVariables(components);
    if (n) components[0].example = { body_text: [Array.from({ length: n }, (_, k) => ["Ravi", "5 September"][k] ?? `Sample ${k + 1}`)] };
    if (footer) components.push({ type: "FOOTER", text: footer });
    return { id: uid("tmpl"), whatsapp_account_id: ACCOUNT_ID, waba_id: WABA_ID, name, language: "en", category, components, body_variable_count: n, status, meta_template_id: status === "REJECTED" ? null : String(1000000000000000 + Math.floor(rand() * 9e15)), rejected_reason: rejected ?? null, created_at: agoMs((5 + Math.floor(rand() * 20)) * 24 * H) };
  };
  const templates: Template[] = [
    T("appointment_feedback", "UTILITY", "APPROVED", "Hi {{1}}, thank you for visiting Jain Pain Clinic on {{2}}. We'd love your feedback — how was your experience?", "Team Jain Pain Clinic"),
    T("google_review_request", "UTILITY", "APPROVED", "Hi {{1}},\n\nIf you were happy with your consultation with Dr Ashu Kumar Jain, we'd really appreciate your feedback.\n\nPlease tap the link below, rate your experience and write a few words:\n\n⭐ https://g.page/r/Cf94Dec-pic0EBM/review\n\nThank you 🙏", "Team Jain Pain Clinic"),
    T("new_chat_v1", "UTILITY", "APPROVED", "Hello! 👋 Welcome to Jain Pain Clinic. Reply to this message to start a conversation with us."),
    T("back_pain_awareness", "MARKETING", "APPROVED", "Hi {{1}}, back pain shouldn't hold you back. Book a consult this week and get a free posture assessment. Reply BOOK to schedule.", "Reply STOP to opt out"),
    T("pain_reengagement_checkin", "MARKETING", "PENDING", "Hi {{1}}, it's been a while since your last visit. How are you feeling? Reply and we'll help you book a follow-up."),
    T("clinic_doctor_intro", "MARKETING", "REJECTED", "Meet Dr. Jain — 20+ years treating chronic pain. Book now for guaranteed relief!", undefined, "Content violates policy: unsubstantiated medical claims (\"guaranteed relief\")."),
  ];

  // broadcasts
  const broadcasts: Broadcast[] = [];
  const recipients: Record<string, BroadcastRecipient[]> = {};
  const mkBroadcast = (name: string, tmpl: Template, n: number, status: Broadcast["status"], daysAgo: number) => {
    const id = uid("bc");
    const recs: BroadcastRecipient[] = [];
    const statuses: BroadcastRecipient["status"][] = status === "completed" ? ["read", "read", "delivered", "delivered", "sent", "failed", "skipped"] : ["read", "delivered", "sent", "pending", "pending", "pending"];
    // unique recipients: a real send never hits the same number twice
    const pool = [...contacts].sort(() => rand() - 0.5).slice(0, Math.min(n, contacts.length));
    n = pool.length;
    for (let k = 0; k < n; k++) {
      const c = pool[k];
      const st = pick(statuses);
      recs.push({ id: uid("rc"), broadcast_id: id, contact_phone: c.phone, contact_name: c.name, params: tmpl.body_variable_count ? [(c.name ?? "there").split(" ")[0]] : [], status: st, meta_message_id: ["pending", "skipped", "failed"].includes(st) ? null : `wamid.${uid("b").toUpperCase()}`, error: st === "failed" ? "131026: recipient not on WhatsApp" : st === "skipped" ? "opted out" : null, sent_at: ["pending", "skipped"].includes(st) ? null : agoMs(daysAgo * 24 * H - k * 20000) });
    }
    const counts = { total: n, pending: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 };
    recs.forEach((r) => { if (r.status !== "sending") counts[r.status]++; });
    broadcasts.push({ id, whatsapp_account_id: ACCOUNT_ID, name, template_name: tmpl.name, template_language: "en", variable_mapping: tmpl.body_variable_count ? { "1": "@contact.name|there" } : {}, audience: { type: "phones", count: n }, status, counts, created_at: agoMs(daysAgo * 24 * H + H), started_at: agoMs(daysAgo * 24 * H), completed_at: status === "completed" ? agoMs(daysAgo * 24 * H - 10 * M) : null });
    recipients[id] = recs;
  };
  mkBroadcast("Google review — Sep week 1", templates[1], 33, "completed", 3);
  mkBroadcast("Back pain awareness — Sep", templates[3], 48, "paused", 1);

  const account: WhatsAppAccount = {
    id: ACCOUNT_ID, name: "Jain Pain Clinic", phone_number_id: "413298732109887", display_phone_number: "+91 98180 45321",
    whatsapp_business_account_id: WABA_ID, verified_name: "Jain Pain Clinic", quality_rating: "GREEN", status: "connected",
    inactivity_timeout_enabled: true, inactivity_timeout_minutes: 15,
    inactivity_timeout_message: "Your chat was closed due to inactivity. Our team will call you back soon. Send us a message anytime to start over. 🙏",
  };
  const client: ClientSettings = {
    id: "client:bcbd04f544", name: "Jain Pain Clinic", username: "jpc",
    crm_push: { enabled: true, url: "https://crm-relay.example.com/jpc/lead", method: "POST", fire_on: ["completed", "timeout"] },
    disposition_sync: { enabled: true, sheet_name: "Leads", lookback_hours: 72 },
    users: [{ id: "u1", name: "Priya Sharma", email: "priya@jpc.in", role: "admin" }, { id: "u2", name: "Abhijeet", email: "ops@ripplica.com", role: "admin" }],
  };
  const usage: AiUsage = {
    current_month: { month: "2026-09", prompt_tokens: 143009, completion_tokens: 15612, total_tokens: 158621, cached_tokens: 61000, turns: 66, cost_usd: 0.0473 },
    months: [
      { month: "2026-09", prompt_tokens: 143009, completion_tokens: 15612, total_tokens: 158621, cached_tokens: 61000, turns: 66, cost_usd: 0.0473 },
      { month: "2026-08", prompt_tokens: 402110, completion_tokens: 44120, total_tokens: 446230, cached_tokens: 0, turns: 188, cost_usd: 0.1334 },
    ],
    totals: { prompt_tokens: 545119, completion_tokens: 59732, total_tokens: 604851, cached_tokens: 61000, turns: 254, cost_usd: 0.1807 },
  };

  // sanity: body render works for the seeded template message
  void renderTemplateBody;

  return { conversations, messages, notes, crm, contacts, templates, broadcasts, recipients, runs, nodeResponses, account, client, usage };
}
