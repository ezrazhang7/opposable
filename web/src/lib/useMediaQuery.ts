import { useEffect, useState } from "react";

/** Layout decisions that CSS cannot express alone — the computer panel becomes
 *  a slide-over rather than a column, which changes the markup, not the style. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** Below this the three columns stop fitting: the panel slides over instead. */
export const WIDE = "(min-width: 1100px)";
/** Below this the rail starts eating the chat column, so it collapses. */
export const ROOMY = "(min-width: 900px)";
