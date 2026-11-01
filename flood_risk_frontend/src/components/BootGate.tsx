import type { ReactNode } from "react";
import { useBoot, type BootData } from "../hooks/useBoot";
import { BACKEND_COMMANDS } from "../constants";
import { EmptyState, ErrorState, Loading } from "./StateViews";

/** Loads windows + districts once and renders `children(boot)` only when both are usable. */
export function BootGate({ children }: { children: (boot: BootData) => ReactNode }) {
  const boot = useBoot();
  if (boot.status === "loading") return <Loading label="Connecting to the backend…" />;
  if (boot.status === "error") {
    return (
      <ErrorState
        error={boot.error}
        onRetry={boot.reload}
        hint={
          <>
            If the backend is running but answers with an error, its database may not be seeded. Run <code>{BACKEND_COMMANDS.seed}</code>.
          </>
        }
      />
    );
  }
  // An empty windows list is allowed: the map and district details still work without any stored assessments.
  if (boot.data.districts.length === 0) {
    return (
      <EmptyState title="The backend has no districts yet" commands={[BACKEND_COMMANDS.seed, BACKEND_COMMANDS.train, BACKEND_COMMANDS.compute]}>
        The database has no district boundaries, so there is nothing to draw. The boundary file (33 districts) must be loaded into the backend first.
      </EmptyState>
    );
  }
  return <>{children(boot.data)}</>;
}
