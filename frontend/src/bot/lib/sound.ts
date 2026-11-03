// Two-note notification chime via Web Audio (no asset). Never throws.
let ctx: AudioContext | null = null;
function getCtx(): AudioContext | null {
  try {
    if (!ctx) {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      ctx = new Ctor();
    }
    return ctx;
  } catch { return null; }
}

export function playNotificationTone(): void {
  try {
    const c = getCtx();
    if (!c) return;
    if (c.state === "suspended") void c.resume();
    const now = c.currentTime;
    const gain = c.createGain();
    gain.connect(c.destination);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.18, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
    const osc = c.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.setValueAtTime(1175, now + 0.09);
    osc.connect(gain);
    osc.start(now);
    osc.stop(now + 0.19);
  } catch { /* ignore */ }
}

/** Browser notification (if permitted) — the current inbox lacks this. */
export function notify(title: string, body: string): void {
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") new Notification(title, { body });
    else if (Notification.permission === "default") void Notification.requestPermission();
  } catch { /* ignore */ }
}
