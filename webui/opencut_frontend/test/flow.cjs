const { chromium } = require("playwright-core");
const browserOptions = {
  headless: true,
  args: [
    "--disable-dev-shm-usage",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--enable-unsafe-webgpu",
    "--ignore-gpu-blocklist",
  ],
};
browserOptions.args.push(
  ...JSON.parse(process.env.MPT_BROWSER_EXTRA_ARGS || "[]"),
);
if (process.env.MPT_BROWSER_EXECUTABLE)
  browserOptions.executablePath = process.env.MPT_BROWSER_EXECUTABLE;
const base = process.env.MPT_BROWSER_BASE || "http://127.0.0.1:8791";
const fs = require("fs");
const assert = require("assert");
(async () => {
  let browser = await chromium.launch(browserOptions);
  const token = fs.readFileSync(process.env.MPT_BROWSER_TOKEN_FILE, "utf8");
  const auth = { Authorization: "Bearer " + token };
  const errors = [];
  async function open() {
    const context = await browser.newContext({
      viewport: { width: 1500, height: 950 },
      acceptDownloads: true,
    });
    await context.addInitScript(() =>
      localStorage.setItem("hasSeenOnboarding", "true"),
    );
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") console.log("CONSOLE", m.text().slice(0, 200));
    });
    await page.goto(base + "/opencut/#token=" + token);
    await page
      .getByText("Saved to this task", { exact: false })
      .first()
      .waitFor({ timeout: 60000 });
    await page.waitForTimeout(1500);
    return { context, page };
  }
  let { context, page } = await open();
  console.log(
    "loaded genuine OpenCut",
    await page.getByRole("button", { name: "Export", exact: true }).count(),
  );
  const caption = page.getByText("Flowers.", { exact: true }).first();
  await caption.click();
  await page.waitForTimeout(600);
  console.log("TEXTAREAS", await page.locator("textarea").count());
  console.log(
    "PROPERTIES",
    (await page.locator("body").innerText()).slice(-2600),
  );
  const area = page.locator("textarea").first();
  await area.fill("Edited flower caption");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await page.waitForTimeout(1800);
  let state = await (
    await page.request.get(base + "/opencut/api/session", { headers: auth })
  ).json();
  assert(JSON.stringify(state.project).includes("Edited flower caption"));
  console.log("server saved caption edit");
  await page.reload();
  await page
    .getByText("Saved to this task", { exact: false })
    .first()
    .waitFor({ timeout: 60000 });
  await page
    .getByText("Edited flower caption", { exact: true })
    .last()
    .waitFor();
  console.log("reload retained edit");
  await browser.close();
  browser = await chromium.launch(browserOptions);
  ({ context, page } = await open());
  await page
    .getByText("Edited flower caption", { exact: true })
    .last()
    .waitFor();
  console.log("fresh browser restored files and editable tracks");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByText("Format", { exact: true }).click();
  await page
    .getByRole("radio", { name: "WebM (VP9) - Smaller file size" })
    .check();
  await page.getByText("Quality", { exact: true }).click();
  await page.getByRole("radio", { name: "Low - Smallest file size" }).check();
  const download = page.waitForEvent("download", { timeout: 180000 });
  await page
    .getByRole("button", { name: "Export", exact: true })
    .last()
    .click();
  const file = await download;
  await file.saveAs(process.env.MPT_BROWSER_OUTPUT + "/export.webm");
  console.log(
    "native export downloaded",
    fs.statSync(process.env.MPT_BROWSER_OUTPUT + "/export.webm").size,
  );
  await page.screenshot({
    path: process.env.MPT_BROWSER_OUTPUT + "/editor.png",
  });
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log("no page errors");
  // The existing generation UI must also work through the same-origin gateway.
  await page.goto(base + "/?view=tasks");
  await page.waitForTimeout(8000);
  console.log(
    "TASK PAGE",
    (await page.locator("body").innerText()).slice(0, 1800),
  );
  assert(
    (await page.locator("body").innerText()).includes(
      "Import Editable Project",
    ),
  );
  await Promise.race([
    browser.close(),
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ]);
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
