/** Shared Playwright harness for the visual checks in the implementation plan.
 *
 * No browser MCP is available, so every UI step is verified by driving headless
 * Chromium here and reviewing the PNGs in e2e/shots/ before the commit.
 */
import { chromium, type Browser, type Page } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const SHOTS = resolve(HERE, "shots");
export const BASE = process.env.OPPOSABLE_BASE ?? "http://127.0.0.1:8734";

export const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  laptop: { width: 1024, height: 768 },
  tablet: { width: 768, height: 900 },
} as const;

export type Theme = "light" | "dark";

export async function withBrowser<T>(fn: (browser: Browser) => Promise<T>): Promise<T> {
  const browser = await chromium.launch();
  try {
    return await fn(browser);
  } finally {
    await browser.close();
  }
}

/** A page with the theme pinned before first paint, so shots are deterministic. */
export async function openPage(
  browser: Browser,
  opts: { theme?: Theme; viewport?: { width: number; height: number }; path?: string } = {},
): Promise<Page> {
  const theme = opts.theme ?? "light";
  const context = await browser.newContext({
    viewport: opts.viewport ?? VIEWPORTS.desktop,
    colorScheme: theme,
    deviceScaleFactor: 1,
  });
  await context.addInitScript(
    ([t]) => localStorage.setItem("opposable.theme", t as string),
    [theme],
  );
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") console.error(`  [console] ${m.text()}`);
  });
  page.on("pageerror", (e) => console.error(`  [pageerror] ${e.message}`));
  await page.goto(BASE + (opts.path ?? "/"), { waitUntil: "networkidle" });
  return page;
}

export async function shoot(page: Page, name: string): Promise<string> {
  const path = resolve(SHOTS, `${name}.png`);
  mkdirSync(dirname(path), { recursive: true });
  await page.screenshot({ path, fullPage: false });
  console.log(`  shot: e2e/shots/${name}.png`);
  return path;
}
