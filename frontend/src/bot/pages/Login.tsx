import { useState, type FormEvent } from "react";
import { useStore } from "../store";
import InstallApp from "../components/InstallApp";
import wordmark from "../assets/ripplica-wordmark-white.png";

/** Sign-in screen. Layout and wording follow the original Ripplica inbox; the
 *  palette is the CRM's, so it sits with the rest of the app. */
export default function Login() {
  const { login } = useStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password || busy) return;
    setBusy(true);
    setError(null);
    try { await login(username.trim(), password); }
    catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
    finally { setBusy(false); }
  }

  const inputCls = "mb-3 w-full rounded-lg border border-line bg-panel2 px-3 py-2.5 text-[14px] outline-none focus:border-accent/60";

  return (
    <div className="flex h-dvh w-screen items-center justify-center bg-bg px-4 text-ink">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6 shadow-2xl">
        <img src={wordmark} alt="Ripplica" className="brand-mark mx-auto mb-5 h-8" />
        <h1 className="mb-1 text-[18px] font-semibold tracking-tight">Sign in</h1>
        <p className="mb-4 text-[12px] text-muted">Enter your inbox credentials.</p>

        <label className="mb-1 block text-[12px] text-muted">Username</label>
        <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={inputCls} />

        <label className="mb-1 block text-[12px] text-muted">Password</label>
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} />

        {error && <p className="mb-3 text-[12px] text-red-400">{error}</p>}

        <button type="submit" disabled={busy || !username.trim() || !password} className="w-full rounded-lg bg-accent px-3 py-2.5 text-[14px] font-semibold text-accent-fg disabled:opacity-40">
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <InstallApp className="mt-3" />
      </form>
    </div>
  );
}
