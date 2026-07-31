/** Screenshot sweep of the running UI: `npm run snap [name-prefix]`.
 *
 * Assumes a server is already up at OPPOSABLE_BASE (default :8734).
 */
import { openPage, shoot, withBrowser, VIEWPORTS, type Theme } from "./shoot";

const prefix = process.argv[2] ?? "app";

await withBrowser(async (browser) => {
  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await shoot(page, `${prefix}-${theme}`);
    await page.context().close();
  }
  const laptop = await openPage(browser, { theme: "light", viewport: VIEWPORTS.laptop });
  await shoot(laptop, `${prefix}-1024`);
  await laptop.context().close();
});
