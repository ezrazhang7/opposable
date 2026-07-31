/** End-to-end happy path: create → watch live → complete → replay.
 *
 *     npm run e2e
 *
 * Self-contained on purpose. It starts its own fixture server (the real bridge
 * with a scripted model) on its own port and temp directory, drives headless
 * Chromium against the built bundle, and exits non-zero on the first failed
 * check — so it can be run twice in a row, or in CI, and mean the same thing.
 */
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Browser, type Page } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.OPPOSABLE_E2E_PORT ?? 8799);
const PAGE_PORT = Number(process.env.OPPOSABLE_E2E_PAGE_PORT ?? 8902);
const PYTHON = process.env.OPPOSABLE_PYTHON ?? "python";
const BASE = `http://127.0.0.1:${PORT}`;
const TASK = "Research the Voyager program and write a briefing with sources.";

let failures = 0;
let checks = 0;

function check(name: string, ok: boolean, detail = "") {
  checks += 1;
  if (ok) {
    console.log(`  ok   ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

async function startServer(dir: string): Promise<ChildProcess> {
  const proc = spawn(
    PYTHON,
    [
      join(HERE, "fixture_server.py"),
      "--port", String(PORT),
      "--page-port", String(PAGE_PORT),
      "--dir", dir,
      "--delay", "0.25",
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  proc.stderr?.on("data", (b) => process.stderr.write(`  [server] ${b}`));

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) throw new Error(`fixture server exited (${proc.exitCode})`);
    try {
      const res = await fetch(`${BASE}/api/tasks`);
      if (res.ok) return proc;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error("fixture server never came up");
}

async function newPage(browser: Browser, errors: string[]): Promise<Page> {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
  });
  const page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(BASE, { waitUntil: "networkidle" });
  return page;
}

const dir = mkdtempSync(join(tmpdir(), "opposable-e2e-"));
let server: ChildProcess | undefined;
let browser: Browser | undefined;
const consoleErrors: string[] = [];

try {
  server = await startServer(dir);
  browser = await chromium.launch();
  const page = await newPage(browser, consoleErrors);
  const panel = page.getByRole("complementary", { name: "opposable's computer" });

  // ---------------------------------------------------------------- create
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.getByRole("textbox").first().fill(TASK);
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: /Working/ }).first().waitFor({ timeout: 30_000 });
  check("submitting from home starts a task", true);

  const listed = await fetch(`${BASE}/api/tasks`).then((r) => r.json());
  check("the task exists on the server", listed.length === 1, `saw ${listed.length}`);
  const taskId: string = listed[0].id;

  // ------------------------------------------------------------- watch live
  await page.getByRole("button", { name: /Updating plan/ }).first().waitFor({ timeout: 30_000 });
  check("a tool call appears as an action chip", true);

  // Live follow means the scrubber sits on the newest step for the whole run:
  // position always equals the total. Waiting for a particular tool to be
  // current instead would race the run.
  await page.waitForFunction(
    () => {
      const label = [...document.querySelectorAll("footer span")]
        .map((s) => s.textContent?.trim() ?? "")
        .find((t) => /^\d+\/\d+$/.test(t));
      if (!label) return false;
      const [at, total] = label.split("/").map(Number);
      return total >= 2 && at === total;
    },
    { timeout: 30_000 },
  );
  check("the computer panel follows the live step", true);

  await page.getByRole("button", { name: /Task progress \d\/5/ }).waitFor({ timeout: 30_000 });
  check("plan progress tracks todo.md", true);

  // The scripted run reads a mistyped path on purpose; the chip must keep the
  // failure on screen rather than swallowing it.
  await page.getByText("Tool error").first().waitFor({ timeout: 30_000 });
  check("a failed tool keeps its error visible", true);

  // --------------------------------------------------------------- complete
  const card = page.getByRole("region", { name: "Task complete" });
  await card.waitFor({ timeout: 60_000 });
  check("the completion card arrives", true);

  await page.getByRole("button", { name: /Task progress 5\/5/ }).waitFor();
  check("the plan finishes checked off", true);

  await page.getByRole("button", { name: /Executing command ls -la/ }).click();
  await panel.getByText("exit 0").waitFor({ timeout: 15_000 });
  check("a shell step renders with its exit code", true);

  await card.getByRole("button", { name: "report.md", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Task files" });
  await drawer.getByText("Voyager Program — briefing").first().waitFor({ timeout: 15_000 });
  check("a deliverable opens in the files drawer", true);
  await page.keyboard.press("Escape");

  const status = await fetch(`${BASE}/api/tasks/${taskId}`).then((r) => r.json());
  check("the server recorded completion", status.status === "complete", status.status);

  await page.context().close();

  // ----------------------------------------------------------------- replay
  const replay = await newPage(browser, consoleErrors);
  await replay.locator('nav[aria-label="Sessions"] li button').first().click();
  await replay.getByRole("region", { name: "Task complete" }).waitFor({ timeout: 30_000 });
  check("a reloaded session replays its history", true);

  const slider = replay.getByLabel("Step", { exact: true });
  await slider.fill("0");
  await replay
    .getByRole("complementary", { name: "opposable's computer" })
    .getByText("Fetch the mission overview page")
    .waitFor({ timeout: 15_000 });
  check("scrubbing to the first step shows that step's plan", true);

  await replay.getByRole("button", { name: "Next step" }).click();
  await replay
    .getByRole("complementary", { name: "opposable's computer" })
    .getByText("Voyager 1 and Voyager 2 launched in 1977", { exact: false })
    .waitFor({ timeout: 15_000 });
  check("stepping forward shows the page it read", true);

  await replay.getByRole("button", { name: "Live", exact: true }).click();
  const liveDisabled = await replay
    .getByRole("button", { name: "Live", exact: true })
    .isDisabled();
  check("Live returns to the newest step", liveDisabled);

  check("no console errors", consoleErrors.length === 0, consoleErrors.join(" | "));

  if (failures) {
    await replay.screenshot({ path: resolve(HERE, "shots", "e2e-failure.png") });
  }
  await replay.context().close();
} catch (err) {
  failures += 1;
  console.log(`  FAIL harness — ${err instanceof Error ? err.message : String(err)}`);
} finally {
  await browser?.close();
  server?.kill();
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    // Windows can hold the sandbox files briefly; the temp dir is disposable.
  }
}

console.log(failures ? `\n${failures}/${checks} checks failed` : `\n${checks}/${checks} checks passed`);
process.exit(failures ? 1 : 0);
