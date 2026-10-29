/** Record a genuine live turn. No API mocking, credential persistence, or traces. */
import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const work = path.resolve(process.env.DEMO_WORK_DIR || 'work');
const baseURL = process.env.DEMO_URL || 'http://127.0.0.1:3000';
const question = 'Which 5 products generated the most revenue in 2017?';
const token = process.env.DEMO_TOKEN_FILE
  ? (await readFile(process.env.DEMO_TOKEN_FILE, 'utf8')).trim()
  : '';
await mkdir(work, { recursive: true });
const browser = await chromium.launch({ headless: true });
let context;
try {
  context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    recordVideo: { dir: work, size: { width: 1600, height: 900 } },
    locale: 'en-US',
    colorScheme: 'dark',
  });
  // Only attach a disposable local token to this app's API, never to CDN requests.
  if (token) {
    await context.route(`${new URL(baseURL).origin}/api/**`, route => route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${token}` },
    }));
  }
  await context.addInitScript(() => {
    localStorage.setItem('trading-desk', JSON.stringify({
      state: { engine: 'cloud', provider: 'openai', model: 'gpt-4.1-mini', sidebarOpen: false, artifactWidth: 760 },
      version: 0,
    }));
  });
  const page = await context.newPage();
  const video = page.video();
  const started = Date.now();
  const stamp = () => (Date.now() - started) / 1000;
  const marks = {};
  const events = [];
  const responses = [];
  page.on('response', response => {
    if (response.url() === `${baseURL}/api/chat`) {
      responses.push((async () => {
        if (!response.ok()) throw new Error(`Chat failed: HTTP ${response.status()}`);
        const text = await response.text();
        for (const frame of text.split('\n\n')) {
          const data = frame.split('\n').find(line => line.startsWith('data:'));
          if (data) events.push(JSON.parse(data.slice(5).trim()));
        }
      })());
    }
  });
  await page.goto(baseURL);
  await page.getByRole('heading', { name: 'Ask the ledger.' }).waitFor();
  await page.getByRole('button', { name: 'Run', exact: true }).waitFor();
  await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(3000);
  marks.ready = stamp();
  await page.waitForTimeout(1500);
  const composer = page.locator('textarea');
  await composer.click();
  await composer.pressSequentially(question, { delay: 55 });
  await page.waitForTimeout(900);
  marks.submit = stamp();
  await composer.press('Enter');
  await page.getByText('Done', { exact: true }).waitFor({ timeout: 180000 });
  await Promise.all(responses);
  if (!events.some(e => e.type === 'table' && e.rows.length === 5)) throw new Error('Expected five real result rows');
  if (events.some(e => e.type === 'error')) throw new Error('Agent returned an error');
  await writeFile(path.join(work, 'turn.json'), JSON.stringify({ question, events }, null, 2));
  await page.locator('aside .monaco-editor').first().waitFor({ timeout: 30000 });
  await page.locator('aside canvas[data-zr-dom-id]').first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(2000);
  marks.results = stamp();
  await page.screenshot({ path: path.join(work, 'results.png') });
  await page.waitForTimeout(4500);
  marks.chart = stamp();
  await page.locator('aside canvas[data-zr-dom-id]').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);
  marks.chartSettled = stamp();
  await page.screenshot({ path: path.join(work, 'chart.png') });
  await page.waitForTimeout(6500);
  marks.end = stamp();
  await context.close();
  context = null;
  await video.saveAs(path.join(work, 'capture.webm'));
  await writeFile(path.join(work, 'turn.json'), JSON.stringify({ question, events }, null, 2));
  await writeFile(path.join(work, 'timing.json'), JSON.stringify(marks, null, 2));
  console.log(`Captured real UI and ${events.length} events in ${work}`);
} finally {
  if (context) await context.close();
  await browser.close();
}
