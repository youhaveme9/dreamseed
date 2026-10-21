"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require(
  process.env.DREAMSEED_PLAYWRIGHT_PATH || "playwright",
);
const site = path.resolve(__dirname, "../site");
const output = path.resolve(__dirname, "../build/site-qa");
const types = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".json": "application/json",
};

async function main() {
  await fs.mkdir(output, { recursive: true });
  const server = http.createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(request.url, "http://localhost").pathname,
      );
      if (!pathname.startsWith("/dreamseed/")) throw new Error("Unknown path");
      const file = path.resolve(site, pathname.slice(11) || "index.html");
      if (!file.startsWith(site + path.sep)) throw new Error("Unknown path");
      const data = await fs.readFile(file);
      response.writeHead(200, {
        "Content-Type": types[path.extname(file)] || "application/octet-stream",
      });
      response.end(data);
    } catch {
      response.writeHead(404);
      response.end("Not found");
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      ...(process.env.DREAMSEED_CHROMIUM_PATH
        ? { executablePath: process.env.DREAMSEED_CHROMIUM_PATH }
        : {}),
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: "reduce",
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400)
        errors.push(`${response.status()} ${response.url()}`);
    });
    const url = `http://127.0.0.1:${server.address().port}/dreamseed/`;
    await page.goto(url, { waitUntil: "networkidle" });
    assert.match(await page.title(), /DreamSeed/);
    assert.equal(await page.locator("h1").count(), 1);
    for (const width of [1440, 1024, 768, 620, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `Horizontal overflow at ${width}px`,
      );
      assert(
        await page
          .locator("img")
          .evaluateAll((images) =>
            images.every((image) => image.complete && image.naturalWidth > 0),
          ),
        `Broken image at ${width}px`,
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator(".menu-toggle").click();
    assert.equal(
      await page.locator(".menu-toggle").getAttribute("aria-expanded"),
      "true",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator(".menu-toggle").getAttribute("aria-expanded"),
      "false",
    );
    await page.locator(".menu-toggle").click();
    await page.locator("#navigation-links a[href='#examples']").click();
    assert.equal(
      await page.locator(".menu-toggle").getAttribute("aria-expanded"),
      "false",
    );
    for (const id of [
      "prompt-cherry",
      "prompt-outpost",
      "prompt-peaks",
      "verified-seed",
    ]) {
      await page.locator(`[data-copy="${id}"]`).click();
      const expected = (await page.locator(`#${id}`).textContent()).trim();
      await page.waitForFunction(
        (text) =>
          navigator.clipboard.readText().then((actual) => actual === text),
        expected,
      );
    }
    assert.equal(
      await page.evaluate(() => navigator.clipboard.readText()),
      "-3989987067671208281",
    );
    for (const tab of ["source", "codex", "claude", "cli"]) {
      await page.locator(`#tab-${tab}`).click();
      assert.equal(await page.locator("[role=tabpanel]:visible").count(), 1);
      assert.equal(
        await page.locator(`#tab-${tab}`).getAttribute("aria-selected"),
        "true",
      );
      assert.equal(
        await page.locator("#copy-install").getAttribute("data-copy"),
        `install-${tab}`,
      );
      await page.locator("#copy-install").click();
      const expected = (
        await page.locator(`#install-${tab}`).textContent()
      ).trim();
      await page.waitForFunction(
        (text) =>
          navigator.clipboard.readText().then((actual) => actual === text),
        expected,
      );
    }
    await page.locator("#tab-source").focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(
      await page.locator("#tab-codex").getAttribute("aria-selected"),
      "true",
    );
    await page.keyboard.press("End");
    assert.equal(
      await page.locator("#tab-cli").getAttribute("aria-selected"),
      "true",
    );
    await page.keyboard.press("Home");
    assert.equal(
      await page.locator("#tab-source").getAttribute("aria-selected"),
      "true",
    );
    await page.locator(".faq-list details").nth(1).locator("summary").click();
    assert.equal(await page.locator(".faq-list details[open]").count(), 1);
    assert.match(
      await page.locator(".faq-list details[open] p").textContent(),
      /actual\s+world\s+spawn\s+elsewhere/,
    );
    await page.locator(".faq-list details[open] summary").click();
    await page.waitForFunction(
      () =>
        !document.getElementById("copy-status").classList.contains("visible"),
    );
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({
      path: path.join(output, "mobile.png"),
      fullPage: true,
    });
    await page.screenshot({ path: path.join(output, "mobile-viewport.png") });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({
      path: path.join(output, "desktop.png"),
      fullPage: true,
    });
    await page.screenshot({ path: path.join(output, "desktop-viewport.png") });
    if (process.env.DREAMSEED_AXE_PATH) {
      await page.addScriptTag({ path: process.env.DREAMSEED_AXE_PATH });
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        for (const tab of ["source", "codex", "claude", "cli"]) {
          await page.locator(`#tab-${tab}`).click();
          const report = await page.evaluate(() =>
            axe.run(document, {
              runOnly: {
                type: "tag",
                values: ["wcag2a", "wcag2aa", "wcag21aa"],
              },
            }),
          );
          await fs.writeFile(
            path.join(output, `accessibility-${width}-${tab}.json`),
            JSON.stringify(report, null, 2),
          );
          assert.deepEqual(
            report.violations.map(({ id, nodes }) => ({
              id,
              nodes: nodes.map(({ target, failureSummary }) => ({
                target,
                failureSummary,
              })),
            })),
            [],
            `Accessibility checks at ${width}px, ${tab} tab`,
          );
        }
      }
      console.log(
        "Automated accessibility checks passed at desktop and mobile widths across all four setup tabs.",
      );
    }
    assert.deepEqual(errors, [], "Browser errors or failed requests");
    await context.close();
    const noScript = await browser.newContext({ javaScriptEnabled: false });
    const plainPage = await noScript.newPage();
    await plainPage.goto(url);
    assert(await plainPage.locator("#install-source").isVisible());
    assert(await plainPage.locator("#verified-seed").isVisible());
    await noScript.close();
    console.log(
      "Browser checks passed: six viewport widths, all images, mobile navigation, eight clipboard actions, four setup tabs, keyboard navigation, FAQ, project path hosting, and content without JavaScript.",
    );
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
