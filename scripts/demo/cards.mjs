import { chromium } from 'playwright';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';

const work = path.resolve(process.env.DEMO_WORK_DIR || 'work');
await mkdir(work, { recursive: true });
const icon = await readFile(new URL('../../frontend/app/icon.svg', import.meta.url), 'utf8');
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  for (const [name, title, sub, footer] of [
    ['intro', 'Ask your data.<br><span>See the SQL.</span>', 'Plain-language questions. Tables. Charts. Clear answers.', 'NORTHWIND SAMPLE DATA · REAL APP FOOTAGE'],
    ['outro', 'Your next insight.<br><span>One question away.</span>', 'Explore Northwind Copilot on GitHub', 'github.com/mostafa7arafa/northwind-copilot'],
  ]) {
    await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8"><style>
      *{box-sizing:border-box}body{margin:0;background:#080a0f;color:#eef1f8;font-family:Arial,sans-serif}
      .card{height:1080px;padding:100px 150px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 86% 40%,#16316477,transparent 58%)}
      .grid{position:absolute;inset:0;opacity:.12;background-image:linear-gradient(#53648a44 1px,transparent 1px),linear-gradient(90deg,#53648a44 1px,transparent 1px);background-size:64px 64px}
      .content{position:relative}.brand{display:flex;align-items:center;gap:22px;font:24px monospace;letter-spacing:5px;color:#c4cddd}.brand svg{width:64px;height:64px}
      h1{font-size:112px;line-height:1.12;letter-spacing:-5px;margin:110px 0 36px;font-weight:600}h1 span{color:#629aff}
      p{font-size:30px;color:#a3adbf;line-height:1.6;margin:0}.footer{position:absolute;bottom:96px;left:150px;border-top:1px solid #2c3850;width:1620px;padding-top:28px;font:21px monospace;letter-spacing:2px;color:#a7b8d5}
      .accent{position:absolute;right:150px;top:240px;width:5px;height:390px;background:linear-gradient(transparent,#629aff,transparent)}
      </style><div class="card"><div class="grid"></div><div class="content"><div class="brand">${icon} NORTHWIND COPILOT</div><h1>${title}</h1><p>${sub}</p></div><div class="accent"></div><div class="footer">${footer}</div></div></html>`);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(work, `${name}.png`) });
  }
} finally {
  await browser.close();
}
