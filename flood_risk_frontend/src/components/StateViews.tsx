import type { ReactNode } from "react";
import { ApiError, apiBaseUrl } from "../api/client";
import { BACKEND_COMMANDS } from "../constants";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

export function CommandList({ commands }: { commands: string[] }) {
  return (
    <ol className="commands">
      {commands.map((c) => (
        <li key={c}>
          <code>{c}</code>
        </li>
      ))}
    </ol>
  );
}

export function EmptyState({ title, children, commands }: { title: string; children?: ReactNode; commands?: string[] }) {
  return (
    <div className="state state-empty" role="status">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {commands && commands.length > 0 && (
        <>
          <p>Run these in the backend folder (with its virtual environment active):</p>
          <CommandList commands={commands} />
        </>
      )}
    </div>
  );
}

export function isNetworkError(e: unknown): boolean {
  return e instanceof ApiError && e.kind === "network";
}

/** "Backend not running" for network failures; status + backend message for HTTP errors. */
export function ErrorState({ error, onRetry, hint }: { error: unknown; onRetry?: () => void; hint?: ReactNode }) {
  if (isNetworkError(error)) {
    return (
      <div className="state state-error" role="alert">
        <h3>Can't reach the backend</h3>
        <p>
          The dashboard tried <code>{apiBaseUrl()}</code> and got no answer. The backend is probably not running, or the address is wrong.
          The browser also blocks the request (it looks identical from here) if this page was opened from an address the backend does not allow:
          the backend allows <code>http://localhost:5173</code> and <code>http://localhost:3000</code>, so open the dashboard there rather than on 127.0.0.1.
        </p>
        <p>Start it from the backend folder:</p>
        <CommandList commands={[BACKEND_COMMANDS.run]} />
        <p>
          If it runs on another address, set <code>VITE_API_BASE_URL</code> in <code>.env</code> and restart <code>npm run dev</code>.
        </p>
        {onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }
  const status = error instanceof ApiError ? error.status : null;
  const detail = error instanceof ApiError ? error.detail : error instanceof Error ? error.message : "Unexpected error";
  return (
    <div className="state state-error" role="alert">
      <h3>Something went wrong{status ? ` (HTTP ${status})` : ""}</h3>
      <p>{detail}</p>
      {hint && <p>{hint}</p>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** True when an error is the backend's 404 "nothing computed" answer. */
export function isNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.kind === "http" && e.status === 404;
}
