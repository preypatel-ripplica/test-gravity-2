import { useEffect, useRef, useState } from "react";

// Only one voice note plays at a time across the whole inbox (like WhatsApp).
let activeAudio: HTMLAudioElement | null = null;

export function mmss(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const t = Math.floor(seconds);
  return `${Math.floor(t / 60)}:${(t % 60).toString().padStart(2, "0")}`;
}

// Deterministic (fake) waveform from the message id — stable, no decoding.
function waveformBars(seed: string, count: number): number[] {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) { h ^= seed.charCodeAt(i); h = Math.imul(h, 16777619); }
  const bars: number[] = [];
  for (let i = 0; i < count; i++) {
    h ^= h << 13; h ^= h >>> 17; h ^= h << 5;
    bars.push(0.28 + (((h >>> 0) % 1000) / 1000) * 0.72);
  }
  return bars;
}
const BAR_COUNT = 34;

export default function VoiceMessage({ src, seed, voice, duration: hint }: { src: string; seed: string; voice?: boolean; duration?: number }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(hint ?? 0);
  const dragging = useRef(false);
  const bars = waveformBars(seed, BAR_COUNT);
  const ratio = duration > 0 ? Math.min(current / duration, 1) : 0;

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => !dragging.current && setCurrent(el.currentTime);
    const onMeta = () => Number.isFinite(el.duration) && el.duration !== Infinity && setDuration(el.duration);
    const onEnd = () => { setPlaying(false); setCurrent(0); if (activeAudio === el) activeAudio = null; };
    const onPause = () => setPlaying(false);
    const onPlay = () => setPlaying(true);
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("loadedmetadata", onMeta);
    el.addEventListener("durationchange", onMeta);
    el.addEventListener("ended", onEnd);
    el.addEventListener("pause", onPause);
    el.addEventListener("play", onPlay);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("loadedmetadata", onMeta);
      el.removeEventListener("durationchange", onMeta);
      el.removeEventListener("ended", onEnd);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("play", onPlay);
      if (activeAudio === el) activeAudio = null;
    };
  }, []);

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) { if (activeAudio && activeAudio !== el) activeAudio.pause(); activeAudio = el; void el.play(); }
    else el.pause();
  };
  const seek = (clientX: number) => {
    const el = audioRef.current, bar = barRef.current;
    if (!el || !bar || !(duration > 0)) return;
    const r = bar.getBoundingClientRect();
    const p = Math.min(Math.max((clientX - r.left) / r.width, 0), 1);
    el.currentTime = p * duration;
    setCurrent(el.currentTime);
  };

  return (
    <div className="my-1 flex min-w-[210px] max-w-[260px] items-center gap-2.5">
      <audio ref={audioRef} src={src} preload="metadata" />
      <button type="button" onClick={toggle} title={playing ? "Pause" : "Play"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-black/20 hover:bg-black/35">
        {playing ? (
          <svg width="14" height="14" viewBox="0 0 12 12" fill="currentColor"><rect x="2" y="1.5" width="3" height="9" rx="1" /><rect x="7" y="1.5" width="3" height="9" rx="1" /></svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 12 12" fill="currentColor"><path d="M3 1.8v8.4a.6.6 0 0 0 .92.5l6.5-4.2a.6.6 0 0 0 0-1L3.92 1.3A.6.6 0 0 0 3 1.8Z" /></svg>
        )}
      </button>
      <div className="min-w-0 flex-1">
        <div
          ref={barRef}
          onPointerDown={(e) => { dragging.current = true; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); seek(e.clientX); }}
          onPointerMove={(e) => dragging.current && seek(e.clientX)}
          onPointerUp={() => (dragging.current = false)}
          className="relative flex h-6 cursor-pointer touch-none select-none items-center gap-[2px]"
        >
          {bars.map((h, i) => (
            <div key={i} className={`flex-1 rounded-full ${i / BAR_COUNT < ratio ? "bg-accent" : "bg-muted/40"}`} style={{ height: `${Math.round(h * 100)}%` }} />
          ))}
          <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent shadow" style={{ left: `${ratio * 100}%` }} />
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted">
          {voice && <span>🎤</span>}
          <span>{mmss(current || 0)}</span>
          {duration > 0 && <><span>/</span><span>{mmss(duration)}</span></>}
        </div>
      </div>
    </div>
  );
}
