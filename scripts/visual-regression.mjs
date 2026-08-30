#!/usr/bin/env node
/**
 * Visual regression over the component gallery (TASKS.md Phase 1-D).
 *
 * The spec asks for the app to be confirmed in light and dark, on small and large screens,
 * with long Japanese text, at larger Dynamic Type sizes and with Reduce Motion on (section
 * 20, section 31 item 11). That is six conditions across a dozen components, which is more
 * than anyone re-checks by hand after the second time. This walks the matrix instead.
 *
 * **What it can and cannot catch.** It compares pixels against committed baselines, so it
 * catches a component that moved, a colour that changed, and text that started clipping —
 * the things a unit test cannot see. It says nothing about whether the design is *good*,
 * and a deliberate change shows up as a failure until the baseline is updated. That is the
 * intended trade: the suite's job is to make every visual change *noticed*.
 *
 * **Rendering is machine-dependent.** Font hashing and antialiasing differ between
 * machines, so baselines generated here will not match pixel-for-pixel elsewhere. The
 * threshold below absorbs antialiasing, not layout. If this ever runs on shared CI it needs
 * a fixed container image; until then it is a local gate and `--update` is how a real change
 * is accepted.
 *
 *   node scripts/visual-regression.mjs            compare against baselines
 *   node scripts/visual-regression.mjs --update   accept the current rendering
 *
 * Assumes the web build is already serving on $PAPERMATCH_WEB_URL (default :8081).
 */
import { mkdirSync, existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import { chromium } from 'playwright';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const BASELINE_DIR = join(ROOT, 'apps/mobile/visual-baselines');
const OUTPUT_DIR = join(ROOT, 'apps/mobile/visual-output');
const BASE_URL = process.env.PAPERMATCH_WEB_URL ?? 'http://localhost:8081';
const UPDATE = process.argv.includes('--update');

/**
 * Per-pixel colour tolerance (0..1). 0.15 is loose enough that antialiasing on a glyph edge
 * does not count and tight enough that a changed text colour does.
 */
const PIXEL_THRESHOLD = 0.15;

/** How many differing pixels are tolerated before a case fails, as a fraction of the frame. */
const FAILURE_RATIO = 0.002;

/**
 * The matrix. Each case names the condition it exists to check, so a failure report says
 * what broke rather than only which file differs.
 */
const CASES = [
  {
    name: 'light-narrow',
    why: 'The everyday case: light theme on a small phone.',
    width: 390,
    height: 1400,
    params: {},
  },
  {
    name: 'dark-narrow',
    why: 'Section 19: dark theme. Catches a hardcoded light colour.',
    width: 390,
    height: 1400,
    params: { theme: 'dark' },
  },
  {
    name: 'light-wide',
    why: 'A large screen: catches a card that stretches instead of centring.',
    width: 820,
    height: 1400,
    params: {},
  },
  {
    name: 'light-small',
    why: 'The smallest phone still supported; where text clips first.',
    width: 320,
    height: 1400,
    params: {},
  },
  {
    name: 'dynamic-type-large',
    why: 'Section 20: Dynamic Type at 1.5×. Catches rows that stop wrapping.',
    width: 390,
    height: 2000,
    params: { fontScale: '1.5' },
  },
  {
    name: 'dynamic-type-max',
    why: 'The clamped maximum. Where a fixed-height control breaks.',
    width: 390,
    height: 2600,
    params: { fontScale: '2' },
  },
  {
    name: 'reduce-motion',
    why: 'Section 20: Reduce Motion. The layout must not change with it.',
    width: 390,
    height: 1400,
    params: { reduceMotion: '1' },
  },
  {
    name: 'english',
    why: 'English strings are longer; catches a label that only fits in Japanese.',
    width: 390,
    height: 1400,
    params: { locale: 'en' },
  },
];

function url(testCase) {
  const query = new URLSearchParams(testCase.params).toString();
  return `${BASE_URL}/dev/visual${query ? `?${query}` : ''}`;
}

/**
 * Wait until every formula frame has reported its height back.
 *
 * The frames are blob-URL iframes that measure themselves and `postMessage` the result; the
 * React side then gives the iframe that height. So a frame still at zero height has not
 * finished rendering, and anything captured now shows a **blank** region where a formula
 * belongs. Blank is the one wrong result that looks like a pass, because it diffs cleanly
 * against a baseline that was itself captured blank — which is exactly what had happened to
 * the `light-wide` baseline.
 */
async function waitForFrames(page, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const pending = await page.evaluate(
      () =>
        [...document.querySelectorAll('iframe')].filter((frame) => frame.clientHeight === 0).length,
    );
    if (pending === 0) return true;
    if (Date.now() >= deadline) {
      console.log(`  note: ${pending} formula frame(s) never reported a height`);
      return false;
    }
    await page.waitForTimeout(250);
  }
}

/**
 * Grow the viewport until the whole gallery fits inside it.
 *
 * `fullPage: true` was the wrong tool here. It stitches by resizing and re-rendering, and a
 * formula frame that is offscreen at capture time is simply never painted — the region comes
 * out blank, and blank is the one failure that reads as a pass, because it matches a
 * baseline that was itself captured blank. Waiting for the frames to report their heights
 * does not fix it either: the height arrives from `postMessage` well before Chromium decides
 * to paint an offscreen frame. Making everything on-screen removes the condition instead of
 * timing around it.
 */
async function fitViewportToPage(page, width) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const needed = await page.evaluate(() =>
      Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
    );
    const current = page.viewportSize();
    if (current !== null && current.height >= needed) return;
    await page.setViewportSize({ width, height: needed });
    // Reflow can lengthen the page again (a formula that now wraps differently), so this
    // measures and grows rather than assuming one pass is enough.
    await page.waitForTimeout(1_500);
  }
}

/**
 * Screenshot, and keep screenshotting until two in a row are identical.
 *
 * A single capture can land mid-paint, and the result is a baseline that records a frame
 * halfway through rendering. Requiring the page to hold still first is what makes a run mean
 * the same thing twice.
 */
async function stableScreenshot(page, attempts = 8) {
  let previous = await page.screenshot();
  for (let index = 1; index < attempts; index += 1) {
    await page.waitForTimeout(500);
    const current = await page.screenshot();
    if (current.equals(previous)) return current;
    previous = current;
  }
  console.log('  note: the page never held still; capturing the last frame anyway');
  return previous;
}

/**
 * Touch every formula frame once more, by element rather than by `window.scrollTo` — the
 * page's scroll lives on an inner container, so scrolling the window moves nothing. Belt and
 * braces now that the viewport already contains the whole page: cheap, and it costs nothing
 * if every frame is already painted.
 */
async function paintFrames(page) {
  const frames = page.locator('iframe');
  const count = await frames.count();
  for (let index = 0; index < count; index += 1) {
    await frames
      .nth(index)
      .scrollIntoViewIfNeeded({ timeout: 10_000 })
      .catch(() => {});
    await page.waitForTimeout(600);
  }
  await page.mouse.wheel(0, -100_000);
  await page.waitForTimeout(1_500);
}

function compare(baseline, current) {
  const a = PNG.sync.read(baseline);
  const b = PNG.sync.read(current);
  if (a.width !== b.width || a.height !== b.height) {
    return {
      changed: Infinity,
      total: 1,
      diff: null,
      reason: `size ${a.width}x${a.height} -> ${b.width}x${b.height}`,
    };
  }
  const diff = new PNG({ width: a.width, height: a.height });
  const changed = pixelmatch(a.data, b.data, diff.data, a.width, a.height, {
    threshold: PIXEL_THRESHOLD,
  });
  return { changed, total: a.width * a.height, diff, reason: null };
}

async function main() {
  mkdirSync(BASELINE_DIR, { recursive: true });
  rmSync(OUTPUT_DIR, { recursive: true, force: true });
  mkdirSync(OUTPUT_DIR, { recursive: true });

  const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM ?? '/opt/pw-browsers/chromium',
    args: [
      '--no-sandbox',
      // Antialiasing that depends on the machine is the main source of false diffs.
      '--font-render-hinting=none',
      '--disable-lcd-text',
      // The formulas live in blob: iframes, which are cross-origin and therefore run
      // out-of-process. A full-page screenshot resizes the viewport and re-renders, and an
      // out-of-process frame does not repaint for it — the formulas came out blank, which
      // reads as a pass because a blank region matches a blank baseline. Keeping the frames
      // in-process is what makes them appear. It weakens the browser's isolation, which is
      // acceptable for a screenshot harness pointed at localhost and would not be in the app.
      '--disable-features=IsolateOrigins,site-per-process',
      '--disable-site-isolation-trials',
    ],
  });

  const failures = [];
  const updated = [];

  for (const testCase of CASES) {
    const page = await browser.newPage({
      viewport: { width: testCase.width, height: testCase.height },
      // Fixed so a locale-dependent date or number cannot move a baseline.
      locale: 'ja-JP',
      timezoneId: 'Asia/Tokyo',
      // The gallery must look the same regardless of what the machine reports.
      colorScheme: 'light',
      reducedMotion: 'no-preference',
    });

    try {
      await page.goto(url(testCase), { waitUntil: 'load', timeout: 180_000 });
      // The formulas render in iframes that report their height back; the layout is not
      // final until that has happened. Waited for rather than timed out on — a fixed delay
      // passed on some runs and captured a blank formula on others, and the run that
      // captured blank was the one that wrote the baseline.
      await waitForFrames(page);

      // Everything on-screen at once, so no frame is ever offscreen at capture time. The
      // sections below the fold are exactly the ones nobody checks by hand, and they are
      // also the ones that came out blank.
      await fitViewportToPage(page, testCase.width);
      await paintFrames(page);
      await waitForFrames(page);

      const current = await stableScreenshot(page);
      const baselinePath = join(BASELINE_DIR, `${testCase.name}.png`);

      if (UPDATE || !existsSync(baselinePath)) {
        writeFileSync(baselinePath, current);
        updated.push(testCase.name);
        console.log(
          `  ${existsSync(baselinePath) && !UPDATE ? 'created' : 'updated'}: ${testCase.name}`,
        );
        continue;
      }

      const { changed, total, diff, reason } = compare(readFileSync(baselinePath), current);
      const ratio = changed / total;
      if (reason !== null || ratio > FAILURE_RATIO) {
        writeFileSync(join(OUTPUT_DIR, `${testCase.name}.actual.png`), current);
        if (diff !== null) {
          writeFileSync(join(OUTPUT_DIR, `${testCase.name}.diff.png`), PNG.sync.write(diff));
        }
        failures.push({ ...testCase, changed, ratio, reason });
        console.log(
          `  FAIL ${testCase.name}: ${reason ?? `${changed} px (${(ratio * 100).toFixed(3)}%)`}`,
        );
      } else {
        console.log(
          `  ok   ${testCase.name}${changed > 0 ? ` (${changed} px, within tolerance)` : ''}`,
        );
      }
    } finally {
      await page.close();
    }
  }

  await browser.close();

  if (updated.length > 0) {
    console.log(`\nBaselines written: ${updated.join(', ')}`);
    console.log('Look at them before committing — an accepted baseline is an accepted design.');
  }

  if (failures.length > 0) {
    console.log('\nDifferences found:');
    for (const failure of failures) {
      console.log(`  ${failure.name} — ${failure.why}`);
      console.log(`    ${failure.reason ?? `${failure.changed} pixels differ`}`);
    }
    console.log(`\nCompare against ${OUTPUT_DIR}. If the change is intended:`);
    console.log('  node scripts/visual-regression.mjs --update');
    process.exit(1);
  }

  console.log('\nNo visual differences.');
}

await main();
