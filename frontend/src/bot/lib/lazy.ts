import { lazy, type ComponentType } from "react";

const RELOAD_FLAG = "crm.chunk-reload";

/**
 * `React.lazy` that survives a release. A page opened before a deploy still
 * holds the old chunk hashes; the first time it asks for a chunk that no longer
 * exists, reload once so it picks up the new shell instead of blanking. A second
 * failure in the same session is a real error and reaches the ErrorBoundary.
 */
export function lazyRetry<T extends ComponentType<unknown>>(importer: () => Promise<{ default: T }>) {
  return lazy(async () => {
    try {
      const mod = await importer();
      try { sessionStorage.removeItem(RELOAD_FLAG); } catch { /* private mode */ }
      return mod;
    } catch (e) {
      let reloaded = false;
      try { reloaded = sessionStorage.getItem(RELOAD_FLAG) === "1"; if (!reloaded) sessionStorage.setItem(RELOAD_FLAG, "1"); } catch { /* private mode */ }
      if (!reloaded) { window.location.reload(); await new Promise(() => { /* page is going away */ }); }
      throw e;
    }
  });
}
