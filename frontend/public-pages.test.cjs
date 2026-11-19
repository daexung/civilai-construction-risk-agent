const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

test('public pages render readable HTML with unique canonical metadata and preserve the private app shell', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'geonsem-public-pages-'));
  try {
    const template = fs.readFileSync(path.join(__dirname, 'public/index.html'), 'utf8');
    fs.writeFileSync(path.join(directory, 'index.html'), template);
    execFileSync(process.execPath, [path.join(__dirname, 'prerender-home.cjs')], {
      env: { ...process.env, BUILD_PATH: directory }, stdio: 'pipe', timeout: 30000,
    });
    const titles = [];
    for (const [page, expected] of [['guide', '선택하고, 확인한 뒤 확정해서 보내요'], ['examples', '보도블록 설치']]) {
      const html = fs.readFileSync(path.join(directory, page, 'index.html'), 'utf8');
      assert.ok(html.includes(`data-prerendered="${page}"`));
      assert.ok(html.includes(expected));
      assert.ok(html.includes(`<link rel="canonical" href="https://www.geonsem.com/${page}"`));
      assert.ok(html.includes(`<meta property="og:url" content="https://www.geonsem.com/${page}"`));
      assert.ok(html.includes('href="/chat?q='));
      assert.ok(!html.includes('beta-notice-backdrop'));
      const structured = JSON.parse(html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
      const webPage = structured['@graph'].find(item => item['@type'] === 'WebPage');
      assert.equal(webPage.url, `https://www.geonsem.com/${page}`);
      assert.equal(webPage.isPartOf['@id'], 'https://www.geonsem.com/#website');
      assert.equal(structured['@graph'].find(item => item['@type'] === 'WebApplication').name, '건셈');
      titles.push(html.match(/<title>([^<]+)<\/title>/)[1]);
    }
    assert.notEqual(titles[0], titles[1]);
    assert.ok(fs.readFileSync(path.join(directory, 'app-shell.html'), 'utf8').includes('<div id="root"></div>'));
    assert.ok(fs.readFileSync(path.join(directory, 'index.html'), 'utf8').includes('data-prerendered="homepage"'));
    const home = fs.readFileSync(path.join(directory, 'index.html'), 'utf8');
    assert.ok(home.includes('건셈에서 무엇을 할 수 있나요?'));
    const homeData = JSON.parse(home.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
    assert.ok(home.includes(homeData['@graph'].find(item => item['@type'] === 'WebApplication').description));
    const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'vercel.json'), 'utf8'));
    const filesystem = config.routes.findIndex(route => route.handle === 'filesystem');
    for (const page of ['guide', 'examples']) {
      const index = config.routes.findIndex(route => route.dest === `/${page}/index.html`);
      assert.ok(index >= 0 && index < filesystem);
      assert.ok(fs.readFileSync(path.join(__dirname, 'public/sitemap.xml'), 'utf8').includes(`https://www.geonsem.com/${page}`));
    }
  } finally {
    assert.equal(path.dirname(directory), path.resolve(os.tmpdir()));
    assert.ok(path.basename(directory).startsWith('geonsem-public-pages-'));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
