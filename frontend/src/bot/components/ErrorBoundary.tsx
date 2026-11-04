import { Component, type ErrorInfo, type ReactNode } from "react";

/** Last line of defence: a render error shows a message instead of a blank page. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("CRM render error", error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-dvh w-screen items-center justify-center bg-bg p-6 text-ink">
        <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-5 shadow-2xl">
          <div className="text-[15px] font-semibold">Something went wrong</div>
          <div className="mt-1 text-[12.5px] text-muted">The page hit an error and stopped. Reloading usually fixes it; if it keeps happening, send this message to support.</div>
          <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-panel2 p-2 text-[11.5px] text-red-500">{this.state.error.message}</pre>
          <button onClick={() => window.location.reload()} className="mt-4 w-full rounded-lg bg-accent px-3 py-2 text-[13px] font-medium text-accent-fg">Reload</button>
        </div>
      </div>
    );
  }
}
