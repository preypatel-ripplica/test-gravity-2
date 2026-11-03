import { useEffect, useState } from "react";
import { useStore } from "../store";
import { Badge, Icon } from "../lib/ui";
import type { Density } from "../types";
import { FEATURE_KEYS, FEATURE_LABELS } from "../features";

const DENSITIES: Density[] = ["compact", "cozy", "comfortable"];
const DLABEL: Record<Density, string> = { compact: "Compact", cozy: "Cozy", comfortable: "Comfortable" };

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (<div className="mb-4"><div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">{title}</div><div className="divide-y divide-line/60 rounded-lg border border-line bg-panel px-3">{children}</div>{hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}</div>);
}
function Field({ label, value, children }: { label: string; value?: React.ReactNode; children?: React.ReactNode }) {
  return (<div className="flex items-center justify-between gap-3 py-2"><span className="shrink-0 text-[12px] text-muted">{label}</span><span className="min-w-0 break-all text-right text-[12.5px] font-medium tabular-nums">{children ?? value}</span></div>);
}
function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${on ? "bg-accent" : "bg-line"}`}>
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${on ? "left-[18px]" : "left-0.5"}`} />
    </button>
  );
}

export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { account, client, theme, toggleTheme, density, setDensity, sound, toggleSound, reset, setToast, remote, logout, features, granted, setFeature, setCallAgents } = useStore();
  const [agents, setAgents] = useState("");
  const savedAgents = (client.call_recording?.agent_names ?? []).join(", ");
  useEffect(() => { setAgents(savedAgents); }, [savedAgents, open]);
  const saveAgents = async () => {
    try { await setCallAgents(agents.split(",")); setToast("Agent names saved"); } catch (e) { setToast(`Could not save: ${(e as Error).message}`); }
  };
  if (!open) return null;
  // Only what Ripplica granted is offered; anything switched off for this client is simply absent.
  const offered = FEATURE_KEYS.filter((k) => granted[k]);

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 sm:items-center" onClick={onClose}>
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div><div className="text-[14px] font-semibold">{client.name}</div><div className="text-[11px] text-muted">@{client.username} · {client.id}</div></div>
          <button onClick={onClose} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <Section title="WhatsApp account">
            <Field label="Status"><Badge color={account.status === "connected" ? "#22c55e" : "#ef4444"}>{account.status}</Badge></Field>
            <Field label="Display name" value={account.verified_name || account.name || "—"} />
            <Field label="Phone number" value={account.display_phone_number || "—"} />
          </Section>

          <Section title="Inactivity timeout (bot auto-close)" hint="Configured by Ripplica for this account.">
            <Field label="Enabled" value={account.inactivity_timeout_enabled ? "On" : "Off"} />
            <Field label="After" value={`${account.inactivity_timeout_minutes} min`} />
            <div className="py-2"><div className="mb-1 text-[12px] text-muted">Closing message</div><div className="whitespace-pre-wrap text-[12.5px]">{account.inactivity_timeout_message || "—"}</div></div>
          </Section>

          <Section title="Users">
            {client.users.map((u) => <Field key={u.id} label={u.name}><span className="text-muted">{u.email} · {u.role}</span></Field>)}
            {client.users.length === 0 && <div className="py-2 text-[12px] text-muted">Signed in as @{client.username || "client"}.</div>}
          </Section>

          {offered.length > 0 && (
            <Section title="Features" hint="Switch off what your team does not use. Applies to everyone signed in as this clinic.">
              {offered.map((k) => (
                <Field key={k} label={FEATURE_LABELS[k]}><Toggle on={features[k]} onChange={(v) => setFeature(k, v)} label={FEATURE_LABELS[k]} /></Field>
              ))}
            </Section>
          )}

          {granted.calls && (
            <Section title="Call recording (FasterQ)" hint="Calls whose agent name matches one of these are attached to this clinic. Ripplica connects FasterQ to us; you only need the names as they appear in FasterQ.">
              <div className="py-2">
                <div className="mb-1 text-[12px] text-muted">Agent names (comma-separated)</div>
                <div className="flex gap-2">
                  <input value={agents} onChange={(e) => setAgents(e.target.value)} placeholder="e.g. Rahul Sharma, Front desk" className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-[12.5px] outline-none focus:border-accent/50" />
                  <button onClick={saveAgents} disabled={agents.trim() === savedAgents.trim()} className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-[12.5px] font-medium text-accent-fg disabled:opacity-40">Save</button>
                </div>
              </div>
            </Section>
          )}

          <Section title="Preferences">
            <Field label="Theme"><button onClick={toggleTheme} className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[12px] text-muted hover:text-ink"><Icon name={theme === "dark" ? "sun" : "moon"} size={14} /> {theme === "dark" ? "Dark" : "Light"}</button></Field>
            <Field label="Density"><div className="flex items-center gap-0.5 rounded-lg border border-line p-0.5">{DENSITIES.map((dd) => <button key={dd} onClick={() => setDensity(dd)} className={`rounded-md px-2 py-0.5 text-[11.5px] ${density === dd ? "bg-accent/15 text-ink" : "text-muted hover:text-ink"}`}>{DLABEL[dd]}</button>)}</div></Field>
            <Field label="Notification sound"><button onClick={toggleSound} className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[12px] text-muted hover:text-ink"><Icon name={sound ? "bell" : "bellOff"} size={14} /> {sound ? "On" : "Off"}</button></Field>
            {!remote && <button onClick={() => { reset(); onClose(); }} className="flex w-full items-center justify-between gap-3 py-2.5 text-left"><span className="text-[12.5px]">Reset demo data</span><Icon name="chevron" size={14} className="text-muted" /></button>}
          </Section>
        </div>

        <div className="border-t border-line px-4 py-3">
          <button onClick={() => { if (remote) { logout(); } else setToast("Logged out (demo)"); onClose(); }} className="w-full rounded-lg border border-line px-3 py-2 text-[13px] font-medium text-red-500 hover:bg-red-500/10">Log out</button>
          <div className="mt-2 text-center text-[11px] text-muted">{remote ? "Ripplica · connected to the live backend" : "Demo data · client-side only · edits persist locally"}</div>
        </div>
      </div>
    </div>
  );
}
