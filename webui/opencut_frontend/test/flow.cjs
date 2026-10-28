const { chromium } = require("playwright-core");
const browserOptions = {
  headless: true,
  args: [
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu-rasterization",
    "--disable-gpu-memory-buffer-video-frames",
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
    await context.addInitScript(() => {
      localStorage.setItem("hasSeenOnboarding", "true");
      // Exercise OpenCut's supported WebGL fallback on CPU CI. Software Dawn
      // cannot reliably copy external image surfaces during native export.
      Object.defineProperty(navigator, "gpu", { value: undefined });
    });
    const page = await context.newPage();
    page.on("pageerror", (e) => {
      errors.push(e.message);
      console.log("PAGE ERROR", e.stack);
    });
    page.on("console", (m) => {
      if (m.type() === "error") console.log("CONSOLE", m.text().slice(0, 1600));
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
  await page.getByRole("button", { name: "Font family", exact: true }).click();
  await page
    .getByRole("button", { name: "Charm-Regular", exact: true })
    .click();
  assert(
    await page.evaluate(() =>
      document.fonts.check('16px "MPT Charm-Regular.ttf"'),
    ),
  );
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await page.waitForTimeout(1800);
  let state = await (
    await page.request.get(base + "/opencut/api/session", { headers: auth })
  ).json();
  assert(JSON.stringify(state.project).includes("Edited flower caption"));
  console.log("server saved caption edit");
  assert(JSON.stringify(state.project).includes("MPT Charm-Regular.ttf"));
  const before = state.project.scenes[0].tracks.main.elements;
  await page.getByText("Scene 1.mp4", { exact: true }).last().click();
  await page.getByLabel("AI clip inspector", { exact: true }).waitFor();
  await page
    .getByLabel("Describe this clip", { exact: true })
    .fill("A new garden variation.");
  await page
    .getByRole("button", { name: "Regenerate clip", exact: true })
    .click();
  await page
    .getByText("Ready to review", { exact: true })
    .waitFor({ timeout: 60000 });
  console.log("candidate preview starting");
  await page
    .getByRole("button", { name: "Preview", exact: true })
    .first()
    .click();
  await page.getByLabel("Candidate preview", { exact: true }).waitFor();
  await page.locator('[aria-label="Candidate preview"] video').evaluate(
    (v) =>
      new Promise((resolve, reject) => {
        if (v.readyState >= 2) return resolve();
        v.onloadeddata = resolve;
        v.onerror = () => reject(new Error("candidate video failed"));
      }),
  );
  console.log("candidate apply starting");
  await page
    .getByRole("button", { name: "Use this version", exact: true })
    .first()
    .click();
  await page.getByText("Selected clip updated.", { exact: false }).waitFor();
  state = await (
    await page.request.get(base + "/opencut/api/session", { headers: auth })
  ).json();
  const after = state.project.scenes[0].tracks.main.elements;
  assert.notEqual(after[0].mediaId, before[0].mediaId);
  assert.equal(after[0].startTime, before[0].startTime);
  assert.equal(after[0].duration, before[0].duration);
  assert.equal(JSON.stringify(after[1]), JSON.stringify(before[1]));
  await page.keyboard.press("Control+z");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await page.waitForTimeout(1000);
  state = await (
    await page.request.get(base + "/opencut/api/session", { headers: auth })
  ).json();
  assert.equal(
    state.project.scenes[0].tracks.main.elements[0].mediaId,
    before[0].mediaId,
  );
  console.log(
    "native clip regenerate/preview/apply/Undo preserved timing and other clips",
  );

  // Native split inherits scene identity, but replacement targets one occurrence.
  await page.getByRole("button", { name: "00:00:00:00", exact: true }).click();
  await page
    .getByPlaceholder("00:00:00:00", { exact: true })
    .fill("00:00:01:00");
  await page.getByPlaceholder("00:00:00:00", { exact: true }).press("Enter");
  await page.keyboard.press("s");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await page.waitForTimeout(800);
  state = await (
    await page.request.get(base + "/opencut/api/session", { headers: auth })
  ).json();
  const split = state.project.scenes[0].tracks.main.elements;
  assert.equal(split.length, 3);
  assert.equal(split.filter((e) => e.mptSceneId === 1).length, 2);
  await page
    .getByRole("button", { name: "Use this version", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  for (let attempt = 0; attempt < 50; attempt++) {
    state = await (
      await page.request.get(base + "/opencut/api/session", { headers: auth })
    ).json();
    const changed = state.project.scenes[0].tracks.main.elements.some(
      (e) => e.mediaId !== split.find((s) => s.id === e.id)?.mediaId,
    );
    if (changed) break;
    await page.waitForTimeout(200);
  }
  const replaced = state.project.scenes[0].tracks.main.elements;
  assert.equal(
    replaced.filter(
      (e) => e.mediaId !== split.find((s) => s.id === e.id).mediaId,
    ).length,
    1,
  );
  for (const e of replaced) {
    const previous = split.find((s) => s.id === e.id);
    assert.equal(e.startTime, previous.startTime);
    assert.equal(e.duration, previous.duration);
    assert.equal(e.trimStart, previous.trimStart);
  }
  await page.keyboard.press("Control+z");
  await page.keyboard.press("Control+z");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await page.waitForTimeout(800);
  console.log(
    "split clip replacement preserved the other occurrence and source trim",
  );

  await page.screenshot({
    path: process.env.MPT_BROWSER_OUTPUT + "/clip-inspector.png",
  });
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
  assert(
    await page.evaluate(() =>
      document.fonts.check('16px "MPT Charm-Regular.ttf"'),
    ),
  );
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
