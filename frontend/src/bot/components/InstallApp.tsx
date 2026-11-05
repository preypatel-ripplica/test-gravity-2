import { useEffect, useState } from "react";

/** Chrome/Edge fire this before showing their own install UI. We keep it so the
 *  login screen can offer Install even when the overflow-menu entry is hidden
 *  (launcher policy, existing shortcut, or Chrome UI reshuffles). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function isStandalone(): boolean {
  if (window.matchMedia("(display-mode: standalone)").matches) return true;
  const nav = navigator as Navigator & { standalone?: boolean };
  return nav.standalone === true;
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  if (/iPad|iPhone|iPod/.test(ua)) return true;
  return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
}

/** Compact install affordance for the bot login (and anywhere else we mount it). */
export default function InstallApp({ className = "" }: { className?: string }) {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [hidden, setHidden] = useState(false);
  const [ios, setIos] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isStandalone()) {
      setHidden(true);
      return;
    }
    setIos(isIos());

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setDeferred(null);
      setHidden(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (hidden) return null;

  async function install() {
    if (!deferred || busy) return;
    setBusy(true);
    try {
      await deferred.prompt();
      const { outcome } = await deferred.userChoice;
      if (outcome === "accepted") setHidden(true);
      setDeferred(null);
    } finally {
      setBusy(false);
    }
  }

  if (deferred) {
    return (
      <button
        type="button"
        onClick={install}
        disabled={busy}
        className={`w-full rounded-lg border border-line bg-panel2 px-3 py-2.5 text-[13px] font-medium text-ink hover:bg-panel disabled:opacity-40 ${className}`}
      >
        {busy ? "Installing…" : "Install app"}
      </button>
    );
  }

  if (ios) {
    return (
      <p className={`text-center text-[11.5px] leading-snug text-muted ${className}`}>
        To install: tap Share, then <span className="text-ink">Add to Home Screen</span>.
      </p>
    );
  }

  // Chrome often hides Install until engagement heuristics pass; point at the
  // current menu path so phones aren't stuck waiting for beforeinstallprompt.
  return (
    <p className={`text-center text-[11.5px] leading-snug text-muted ${className}`}>
      To install: Chrome menu → <span className="text-ink">Install and create shortcut</span> → Install.
    </p>
  );
}
