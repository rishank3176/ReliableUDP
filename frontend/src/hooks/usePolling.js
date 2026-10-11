import { useEffect } from "react";

export function usePolling(callback, delay, enabled = true) {
  useEffect(() => {
    if (!enabled || delay === null) return undefined;
    const timer = setInterval(callback, delay);
    return () => clearInterval(timer);
  }, [callback, delay, enabled]);
}
