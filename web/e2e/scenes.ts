/** Named visual scenes, one per implementation step. `npm run snap <scene>`
 *  drives the real UI and writes PNGs to e2e/shots/ for review before commit. */
import type { Browser, Page } from "playwright";
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

/** The newest task is first in the rail, so scenes can open what they made. */
async function selectNewest(page: Page) {
  await page.locator('nav[aria-label="Sessions"] li button').first().click();
}

/** A live run, then the same session after it finishes. */
const chat: Scene = async (browser) => {
  const task = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );

  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);
  await page.getByText("Executing command").first().waitFor({ timeout: 30_000 });
  await shoot(page, "chat-live");

  await waitForStatus(task.id, "complete");
  await page.waitForTimeout(400);
  await shoot(page, "chat-complete");

  await page.context().close();

  const dark = await openPage(browser, { theme: "dark" });
  await selectNewest(dark);
  await dark.getByText("Tool error").first().waitFor();
  await shoot(dark, "chat-complete-dark");
  await dark.context().close();

  // A stream taller than the viewport: scrolling up must stop the auto-follow
  // and offer the jump-to-latest pill.
  const long = await createTask("Crawl the archive index and summarise it.", "long");
  await waitForEvents(long.id, 40);
  const tall = await openPage(browser, { theme: "light" });
  await selectNewest(tall);
  await tall.waitForFunction(() => {
    const el = document.querySelector("main .overflow-y-auto");
    return !!el && el.scrollHeight > el.clientHeight + 200;
  }, { timeout: 30_000 });
  await tall.locator("main .overflow-y-auto").first().evaluate((el) => el.scrollTo({ top: 0 }));
  await tall.waitForTimeout(500);
  await shoot(tall, "chat-jump-pill");
  await stopTask(long.id);
  await tall.context().close();

  // A deliberately tiny context budget forces the ledger to spill observations
  // to disk, which the stream reports as a dim compress line.
  const squeezed = await createTask("Crawl with almost no context budget.", "long", {
    budget_tokens: 200,
  });
  const cramped = await openPage(browser, { theme: "light" });
  await selectNewest(cramped);
  await cramped.getByText(/Compressed \d+ observation/).first().waitFor({ timeout: 30_000 });
  await shoot(cramped, "chat-compress");
  await stopTask(squeezed.id);
  await cramped.context().close();
};

/** The computer panel following a live shell_exec, then pinned to a step. */
const terminal: Scene = async (browser) => {
  const long = await createTask("Crawl the archive index and summarise it.", "long");
  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);
  const panel = page.getByRole("complementary", { name: "opposable's computer" });
  await panel.getByText("exit 0").waitFor({ timeout: 30_000 });
  await shoot(page, "terminal-live");

  // Clicking a chip pins the panel to that step and drops out of live follow.
  await page.getByRole("button", { name: /Executing command echo step 1 / }).click();
  await panel.getByText("step 1 of a long crawl").first().waitFor();
  await shoot(page, "terminal-pinned");

  await page.getByRole("button", { name: "Raw", exact: true }).click();
  await page.waitForTimeout(200);
  await shoot(page, "terminal-raw");

  await page.getByRole("button", { name: "Raw", exact: true }).click();
  await page.getByRole("button", { name: "Live", exact: true }).click();
  await page.waitForTimeout(400);
  await shoot(page, "terminal-back-to-live");
  await stopTask(long.id);
  await page.context().close();

  const dark = await openPage(browser, { theme: "dark" });
  await selectNewest(dark);
  await dark
    .getByRole("complementary", { name: "opposable's computer" })
    .getByText("exit 0")
    .waitFor({ timeout: 30_000 });
  await shoot(dark, "terminal-dark");
  await dark.context().close();
};

/** The editor and reader renderers, on a finished demo run. */
const renderers: Scene = async (browser) => {
  const task = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );
  await waitForStatus(task.id, "complete");

  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await selectNewest(page);
    await page.getByRole("button", { name: /Completing task/ }).waitFor({ timeout: 30_000 });

    await page.getByRole("button", { name: /Writing file report\.md/ }).click();
    await page.waitForTimeout(200);
    await shoot(page, `renderer-editor-write-${theme}`);

    await page.getByRole("button", { name: /Browsing http/ }).click();
    await page.waitForTimeout(200);
    await shoot(page, `renderer-reader-${theme}`);

    await page.getByRole("button", { name: /Reading file notes-typo\.md/ }).click();
    await page.waitForTimeout(200);
    await shoot(page, `renderer-editor-error-${theme}`);

    await page.context().close();
  }
};

/** Plan progress: the counter tracks todo.md as the agent checks items off. */
const plan: Scene = async (browser) => {
  const task = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );

  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);

  // First plan_update: nothing checked off yet.
  await page.getByRole("button", { name: /Task progress 0\/5/ }).waitFor({ timeout: 30_000 });
  await shoot(page, "plan-early");

  await waitForStatus(task.id, "complete");
  await page.getByRole("button", { name: /Task progress 5\/5/ }).waitFor();
  await shoot(page, "plan-complete");

  await page.getByRole("button", { name: /Task progress/ }).click();
  await page.waitForTimeout(200);
  await shoot(page, "plan-checklist");
  await page.keyboard.press("Escape");

  // The plan_ renderer shows the todo.md of the step you pick.
  await page.getByRole("button", { name: /Updating plan/ }).first().click();
  await page.waitForTimeout(200);
  await shoot(page, "plan-renderer");
  await page.context().close();

  const dark = await openPage(browser, { theme: "dark" });
  await selectNewest(dark);
  await dark.getByRole("button", { name: /Task progress 5\/5/ }).waitFor({ timeout: 30_000 });
  await dark.getByRole("button", { name: /Task progress/ }).click();
  await dark.waitForTimeout(200);
  await shoot(dark, "plan-checklist-dark");
  await dark.context().close();
};

/** Reopen a finished session and scrub its timeline. */
const replay: Scene = async (browser) => {
  const task = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );
  await waitForStatus(task.id, "complete");

  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);
  await page.getByRole("button", { name: /Completing task/ }).waitFor({ timeout: 30_000 });

  const slider = page.getByLabel("Step", { exact: true });
  await slider.fill("0");
  await page.waitForTimeout(200);
  await shoot(page, "replay-step-1");

  await page.getByRole("button", { name: "Next step" }).click();
  await page.getByRole("button", { name: "Next step" }).click();
  await page.waitForTimeout(200);
  await shoot(page, "replay-step-3");

  await slider.fill("6");
  await page.waitForTimeout(200);
  await shoot(page, "replay-step-7");

  // Autoplay walks forward on its own at about two steps a second.
  await slider.fill("0");
  await page.getByRole("button", { name: "Replay steps" }).click();
  await page.waitForTimeout(1100);
  await shoot(page, "replay-autoplay");
  await page.getByRole("button", { name: "Pause replay" }).click();

  await page.getByRole("button", { name: "Live", exact: true }).click();
  await page.waitForTimeout(200);
  await shoot(page, "replay-back-to-live");
  await page.context().close();

  const dark = await openPage(browser, { theme: "dark" });
  await selectNewest(dark);
  await dark.getByRole("button", { name: /Completing task/ }).waitFor({ timeout: 30_000 });
  await dark.getByLabel("Step", { exact: true }).fill("2");
  await dark.waitForTimeout(200);
  await shoot(dark, "replay-dark");
  await dark.context().close();
};

/** Completion card, deliverable chips, and the files drawer. */
const files: Scene = async (browser) => {
  const task = await createTask(
    "Research the Voyager program and write a briefing with sources.",
  );
  await waitForStatus(task.id, "complete");

  for (const theme of ["light", "dark"] as Theme[]) {
    const page = await openPage(browser, { theme });
    await selectNewest(page);
    const card = page.getByRole("region", { name: "Task complete" });
    await card.waitFor({ timeout: 30_000 });
    await shoot(page, `completion-card-${theme}`);

    // A deliverable chip opens the drawer straight onto that file.
    await card.getByRole("button", { name: "report.md", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "Task files" });
    await drawer.waitFor();
    await drawer.getByText("Voyager Program — briefing").first().waitFor();
    await shoot(page, `files-drawer-${theme}`);

    await drawer.getByRole("checkbox", { name: "Show internal files" }).check();
    await drawer.getByRole("button", { name: /^todo\.md/ }).first().click();
    await page.waitForTimeout(250);
    await shoot(page, `files-drawer-internal-${theme}`);

    await page.keyboard.press("Escape");
    await page.context().close();
  }

  // The download link serves the file the agent actually wrote.
  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);
  await page
    .getByRole("region", { name: "Task complete" })
    .getByRole("button", { name: "notes.md", exact: true })
    .click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download" }).click();
  const saved = await download;
  console.log(`  downloaded: ${saved.suggestedFilename()}`);
  await page.context().close();

  // An image deliverable previews as an image, not as text.
  const chart = await createTask("Chart launches per decade as an SVG.", "chart");
  await waitForStatus(chart.id, "complete");
  const withImage = await openPage(browser, { theme: "light" });
  await selectNewest(withImage);
  await withImage
    .getByRole("region", { name: "Task complete" })
    .getByRole("button", { name: "chart.svg", exact: true })
    .click();
  await withImage.getByRole("img", { name: "chart.svg" }).waitFor();
  await shoot(withImage, "files-drawer-image");
  await withImage.context().close();
};

/** Stop a run, send guidance, and pick a stopped task back up. */
const controls: Scene = async (browser) => {
  const task = await createTask("Crawl the archive index and summarise it.", "long");
  const page = await openPage(browser, { theme: "light" });
  await selectNewest(page);
  await page.getByRole("button", { name: /Executing command/ }).first().waitFor({
    timeout: 30_000,
  });
  await shoot(page, "controls-running");

  // Guidance lands in the transcript as a user bubble.
  const composer = page.getByRole("textbox", { name: /Send guidance/ });
  await composer.fill("Focus on the 1977 launches only.");
  await composer.press("Enter");
  await page.getByText("Focus on the 1977 launches only.").waitFor();
  await shoot(page, "controls-guidance-sent");

  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await page.getByRole("button", { name: "Resume", exact: true }).waitFor({ timeout: 30_000 });
  await waitForStatus(task.id, "stopped");
  await page.waitForTimeout(400);
  await shoot(page, "controls-stopped");

  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await page.getByRole("button", { name: "Stop", exact: true }).waitFor({ timeout: 30_000 });
  await page.waitForTimeout(600);
  await shoot(page, "controls-resumed");
  await stopTask(task.id);
  await page.context().close();

  // An error status is a badge too: a script that runs out of turns errors.
  const dark = await openPage(browser, { theme: "dark" });
  await selectNewest(dark);
  await dark.getByRole("button", { name: /Executing command/ }).first().waitFor({
    timeout: 30_000,
  });
  await shoot(dark, "controls-dark");
  await dark.context().close();
};

export const scenes: Record<string, Scene> = {
  shell,
  sessions,
  home,
  chat,
  terminal,
  renderers,
  plan,
  replay,
  files,
  controls,
};
