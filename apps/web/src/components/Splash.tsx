import React, { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../motion";

const SEEN_KEY = "nagarsaathi.splash-seen";
const NAME = "NagarSaathi";
const INTRO_MS = 2400;
const EXIT_MS = 1000;

function alreadySeen() {
  try {
    return sessionStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * First-load splash: a centre line is painted, the brand pin drops onto it and the
 * name settles in. On exit the asphalt shrinks into the sidebar while the logo flies
 * onto the sidebar's own brand mark, so the splash hands off to the real UI.
 * Shown once per browser session; click or any key skips it.
 */
export function Splash() {
  const [phase, setPhase] = useState<"intro" | "exit" | "done">(() =>
    prefersReducedMotion() || alreadySeen() ? "done" : "intro",
  );
  const [target, setTarget] = useState<"sidebar" | "top">("sidebar");
  const rootRef = useRef<HTMLDivElement>(null);
  const logoRef = useRef<HTMLSpanElement>(null);
  const leaving = useRef(false);

  function leave() {
    if (leaving.current) return;
    leaving.current = true;
    const root = rootRef.current;
    const logo = logoRef.current?.getBoundingClientRect();
    const sidebar = document.querySelector(".sidebar")?.getBoundingClientRect();
    const mark = document.querySelector(".sidebar .brand-symbol")?.getBoundingClientRect();
    // On phones the sidebar is off-canvas, so the splash lifts away instead.
    if (root && logo && sidebar && mark && sidebar.left >= 0 && mark.width) {
      root.style.setProperty("--fly-x", `${mark.left + mark.width / 2 - (logo.left + logo.width / 2)}px`);
      root.style.setProperty("--fly-y", `${mark.top + mark.height / 2 - (logo.top + logo.height / 2)}px`);
      root.style.setProperty("--fly-scale", String(mark.width / logo.width));
      root.style.setProperty("--panel-cut", `${window.innerWidth - sidebar.right}px`);
      setTarget("sidebar");
    } else {
      setTarget("top");
    }
    setPhase("exit");
    setTimeout(() => setPhase("done"), EXIT_MS);
  }

  useEffect(() => {
    if (phase !== "intro") return;
    try {
      sessionStorage.setItem(SEEN_KEY, "1");
    } catch {
      // Private mode: the splash simply shows again next load.
    }
    const timer = setTimeout(leave, INTRO_MS);
    window.addEventListener("keydown", leave);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", leave);
    };
  }, [phase]);

  if (phase === "done") return null;

  return (
    <div
      ref={rootRef}
      className={`splash ${phase} to-${target}`}
      role="status"
      aria-label="Loading NagarSaathi"
      onClick={leave}
    >
      <div className="splash-stage">
        <div className="splash-mark">
          <span className="splash-road" aria-hidden="true" />
          <span className="splash-logo" ref={logoRef} aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path
                pathLength={1}
                d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"
              />
              <circle pathLength={1} cx="12" cy="10" r="3" />
            </svg>
            <span className="splash-ping" />
          </span>
        </div>
        <div className="splash-name" aria-hidden="true">
          {NAME.split("").map((letter, i) => (
            <span key={i} style={{ "--i": i } as React.CSSProperties}>
              {letter}
            </span>
          ))}
        </div>
        <p className="splash-tagline">Your city, our responsibility</p>
      </div>
    </div>
  );
}
