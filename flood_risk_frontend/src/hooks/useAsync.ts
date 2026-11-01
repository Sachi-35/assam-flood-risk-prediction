import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: undefined; error: undefined }
  | { status: "ok"; data: T; error: undefined }
  | { status: "error"; data: undefined; error: unknown };

/** Runs `fn` whenever `deps` change; ignores results of stale calls. `reload` re-runs it. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading", data: undefined, error: undefined });
  const [tick, setTick] = useState(0);
  const callId = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    const id = ++callId.current;
    setState({ status: "loading", data: undefined, error: undefined });
    fnRef.current().then(
      (data) => {
        if (id === callId.current) setState({ status: "ok", data, error: undefined });
      },
      (error) => {
        if (id === callId.current) setState({ status: "error", data: undefined, error });
      },
    );
    return () => {
      callId.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload } as AsyncState<T> & { reload: () => void };
}
