/** Named visual scenes, one per implementation step. `npm run snap <scene>`
 *  drives the real UI and writes PNGs to e2e/shots/ for review before commit. */
import type { Browser } from "playwright";
import { openPage, shoot, VIEWPORTS, type Theme } from "./shoot";
import { createTask, stopTask, waitForEvents, waitForStatus } from "./tasks";

export type Scene = (browser: Browser) => Promise<void>;

const shell: Scene = async (browser) => {
  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await shoot(page, `shell-${theme}`);
    await page.context().close();
  }

  const collapsed = await openPage(browser, { theme: "light" });
  await collapsed.getByRole("button", { name: "Collapse sidebar" }).click();
  await collapsed.getByRole("button", { name: "Hide computer panel" }).click();
  await collapsed.waitForTimeout(300);
  await shoot(collapsed, "shell-collapsed");
  await collapsed.context().close();

  const laptop = await openPage(browser, { theme: "dark", viewport: VIEWPORTS.laptop });
  await shoot(laptop, "shell-1024");
  await laptop.context().close();
};

/** Three sessions in three different states, so the rail shows every icon. */
const sessions: Scene = async (browser) => {
  const done = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );
  await waitForStatus(done.id, "complete");

  const halted = await createTask("Crawl the archive index and summarise it.", "long");
  await waitForEvents(halted.id, 4);
  await stopTask(halted.id);
  await waitForStatus(halted.id, "stopped");

  const live = await createTask("Build a small dataset of launch dates.", "long");
  await waitForEvents(live.id, 3);

  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await page.getByRole("button", { name: /Research the Voyager/ }).click();
    await shoot(page, `sessions-${theme}`);
    await page.context().close();
  }

  const collapsed = await openPage(browser, { theme: "light" });
  await collapsed.getByRole("button", { name: "Collapse sidebar" }).click();
  await collapsed.waitForTimeout(300);
  await shoot(collapsed, "sessions-collapsed");
  await collapsed.context().close();

  const filtered = await openPage(browser, { theme: "light" });
  await filtered.getByLabel("Search tasks").fill("launch");
  await filtered.waitForTimeout(150);
  await shoot(filtered, "sessions-search");
  await filtered.context().close();
};

/** Home screen, and the round trip from typing a task to it existing. */
const home: Scene = async (browser) => {
  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await shoot(page, `home-${theme}`);
    await page.getByRole("tab", { name: "Code" }).click();
    await page.waitForTimeout(150);
    await shoot(page, `home-${theme}-code-tab`);
    await page.context().close();
  }

  const page = await openPage(browser, { theme: "light" });
  const prompt = "Write a haiku about opposable thumbs and save it to haiku.txt.";
  await page.getByRole("textbox").first().fill(prompt);
  await shoot(page, "home-typed");
  await page.keyboard.press("Enter");

  // Submitting selects the new task: it shows in the header and the rail.
  await page.getByRole("heading", { level: 1 }).waitFor({ state: "detached" });
  await page
    .getByRole("button", { name: /Working Write a haiku/ })
    .first()
    .waitFor();
  await shoot(page, "home-submitted");
  await page.context().close();
};

export const scenes: Record<string, Scene> = { shell, sessions, home };
