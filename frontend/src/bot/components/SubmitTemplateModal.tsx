import { useState } from "react";
import { useStore } from "../store";
import { TEMPLATE_CATEGORIES, type TemplateCategory } from "../types";
import { Icon, CATEGORY_COLOR } from "../lib/ui";
import { countBodyVariables, componentsFrom } from "../lib/templates";
import Select from "./Select";

export default function SubmitTemplateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { submitTemplate, setToast } = useStore();
  const [name, setName] = useState("");
  const [category, setCategory] = useState<TemplateCategory>("UTILITY");
  const [language, setLanguage] = useState("en");
  const [body, setBody] = useState("");
  const [footer, setFooter] = useState("");
  if (!open) return null;
  const nVars = countBodyVariables(componentsFrom(body));
  const reset = () => { setName(""); setCategory("UTILITY"); setLanguage("en"); setBody(""); setFooter(""); };
  const submit = async () => { if (!name.trim() || !body.trim()) return; try { await submitTemplate({ name, category, language, body, footer }); reset(); onClose(); } catch (e) { setToast(`Submit failed: ${(e as Error).message}`); } };
  const inputCls = "w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[13px] outline-none focus:border-accent/50";
  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 sm:items-center" onClick={onClose}>
      <div className="w-full max-w-lg overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-[14px] font-semibold">Submit template to Meta</div>
          <button onClick={onClose} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
        </div>
        <div className="space-y-3 p-4">
          <div><label className="mb-1 block text-[11.5px] text-muted">Template name (lowercase_with_underscores)</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. appointment_reminder" className={inputCls} /></div>
          <div className="flex gap-3">
            <div className="flex-1"><label className="mb-1 block text-[11.5px] text-muted">Category</label><Select label="Category" value={category} onChange={(v) => setCategory(v as TemplateCategory)} options={TEMPLATE_CATEGORIES.map((c) => ({ value: c, label: c, color: CATEGORY_COLOR[c] }))} /></div>
            <div className="w-28"><label className="mb-1 block text-[11.5px] text-muted">Language</label><input value={language} onChange={(e) => setLanguage(e.target.value)} className={inputCls} /></div>
          </div>
          <div><label className="mb-1 block text-[11.5px] text-muted">Body — use {"{{1}}"}, {"{{2}}"} for variables {nVars > 0 && <span className="text-accent">· {nVars} detected</span>}</label><textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="Hi {{1}}, …" className={`${inputCls} resize-none`} /></div>
          <div><label className="mb-1 block text-[11.5px] text-muted">Footer (optional)</label><input value={footer} onChange={(e) => setFooter(e.target.value)} placeholder="e.g. Team Jain Pain Clinic" className={inputCls} /></div>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-line px-4 py-3">
          <button onClick={onClose} className="rounded-lg border border-line px-3 py-1.5 text-[13px] text-muted hover:text-ink">Cancel</button>
          <button onClick={submit} disabled={!name.trim() || !body.trim()} className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-40">Submit for review</button>
        </div>
      </div>
    </div>
  );
}
