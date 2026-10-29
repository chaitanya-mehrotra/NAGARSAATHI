import { useEffect, useRef, useState } from "react";

/** Treat a browser without matchMedia (tests, old engines) like one that asked for less motion. */
export function prefersReducedMotion() {
  return !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Tweens from the last shown number to the new one, so changing a filter visibly re-counts. */
export function CountUp({ value, duration = 900 }: { value: number; duration?: number }) {
  const [shown, setShown] = useState(prefersReducedMotion() ? value : 0);
  const current = useRef(shown);

  useEffect(() => {
    const from = current.current;
    if (prefersReducedMotion() || from === value) {
      current.current = value;
      setShown(value);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 4);
      const next = Math.round(from + (value - from) * eased);
      current.current = next;
      setShown(next);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return <>{shown}</>;
}
