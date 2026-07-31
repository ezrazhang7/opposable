import { useCallback, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "opposable.theme";

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Theme lives on <html> (set pre-paint by the inline script in index.html);
 *  React only flips the class and remembers the choice. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", next === "dark");
      localStorage.setItem(KEY, next);
      return next;
    });
  }, []);
  return [theme, toggle];
}
