import { useEffect, useState } from "react";

/** Full-screen image viewer with download; Escape / backdrop closes. */
export default function Lightbox({ src, filename, caption, onClose }: { src: string; filename?: string; caption?: string; onClose: () => void }) {
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  async function download() {
    if (downloading) return;
    setDownloading(true);
    try {
      const blob = await (await fetch(src)).blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "image";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      window.open(src, "_blank", "noopener");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex flex-col bg-black/90" onClick={onClose}>
      <div className="flex items-center gap-2 px-3 py-2 text-white" onClick={(e) => e.stopPropagation()}>
        <span className="min-w-0 flex-1 truncate text-[13px] text-white/70">{caption || filename || ""}</span>
        <button onClick={download} disabled={downloading} title="Download" className="grid h-10 w-10 place-items-center rounded-full text-[18px] hover:bg-white/10 disabled:opacity-40">⬇</button>
        <button onClick={onClose} title="Close" className="grid h-10 w-10 place-items-center rounded-full text-[20px] hover:bg-white/10">✕</button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center p-2">
        <img src={src} alt={caption || filename || "image"} className="max-h-full max-w-full object-contain" onClick={(e) => e.stopPropagation()} />
      </div>
    </div>
  );
}
