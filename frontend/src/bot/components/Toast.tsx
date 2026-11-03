import { useStore } from "../store";
import { Icon } from "../lib/ui";

export default function Toast() {
  const { toast } = useStore();
  if (!toast) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex justify-center px-4 md:bottom-6">
      <div className="pointer-events-auto flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-[13px] shadow-2xl">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-accent text-accent-fg"><Icon name="check" size={12} /></span>
        {toast}
      </div>
    </div>
  );
}
