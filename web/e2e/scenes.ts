/** Named visual scenes, one per implementation step. `npm run snap <scene>`
 *  drives the real UI and writes PNGs to e2e/shots/ for review before commit. */
import type { Browser } from "playwright";
import { openPage, shoot, VIEWPORTS, type Theme } from "./shoot";

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

export const scenes: Record<string, Scene> = { shell };
