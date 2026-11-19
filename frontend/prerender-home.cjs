/* Build the public home HTML from the exact React component used by the browser. */
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

const frontend = path.resolve(__dirname);
const build = process.env.BUILD_PATH
  ? path.resolve(process.env.BUILD_PATH)
  : path.join(frontend, 'build');

// CRA's TypeScript compiler is already a project dependency. Transpile only the
// landing component tree so App.tsx and its browser-only authentication state
// never run during the build-time HTML render.
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const source = fs.readFileSync(filename, 'utf8');
    const output = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        jsx: ts.JsxEmit.React,
        esModuleInterop: true,
      },
      fileName: filename,
    }).outputText;
    module._compile(output, filename);
  };
}
for (const extension of ['.css', '.scss']) {
  require.extensions[extension] = () => {};
}

const React = require('react');
const { renderToString } = require('react-dom/server');
const Landing = require('./src/landing/Landing').default;
const HelpPage = require('./src/help/HelpPages').default;
const { PUBLIC_PAGE_META } = require('./src/help/publicPageMeta');
const markup = renderToString(React.createElement(Landing, {
  onStart: () => {},
  onExample: () => {},
}));

const indexPath = path.join(build, 'index.html');
const shellPath = path.join(build, 'app-shell.html');
const template = fs.readFileSync(indexPath, 'utf8');
const root = '<div id="root"></div>';
if (template.split(root).length !== 2) {
  throw new Error('Expected exactly one empty CRA root in build/index.html');
}

// Save the normal app shell for every non-home SPA route before replacing the
// root document with the static landing page.
fs.writeFileSync(shellPath, template, 'utf8');
fs.writeFileSync(indexPath,
  template.replace(root, `<div id="root" data-prerendered="homepage">${markup}</div>`),
  'utf8');

const escapeAttribute = value => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
for (const [page, meta] of Object.entries(PUBLIC_PAGE_META)) {
  const url = `https://www.geonsem.com/${page}`;
  let document = template.replace(/<title>[^<]*<\/title>/, `<title>${escapeAttribute(meta.title)}</title>`);
  for (const [name, value] of [['description', meta.description], ['og:title', meta.title], ['og:description', meta.description], ['og:url', url]]) {
    const attribute = name.startsWith('og:') ? 'property' : 'name';
    document = document.replace(new RegExp(`<meta ${attribute}="${name}" content="[^"]*"\\s*\\/?>`),
      `<meta ${attribute}="${name}" content="${escapeAttribute(value)}" />`);
  }
  document = document.replace(/<link rel="canonical" href="[^"]*"\s*\/?>/, `<link rel="canonical" href="${url}" />`);
  const content = renderToString(React.createElement(HelpPage, { page }));
  document = document.replace(root, `<div id="root" data-prerendered="${page}">${content}</div>`);
  const directory = path.join(build, page);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'index.html'), document, 'utf8');
  if (!document.includes(meta.title) || !document.includes(`href="${url}"`)
      || !document.includes('href="/chat') || document.includes('beta-notice-backdrop')) {
    throw new Error(`Public page ${page} failed prerender verification`);
  }
}

const html = fs.readFileSync(indexPath, 'utf8');
const required = [
  '건셈', '공사비 견적', '품셈 상담', '엑셀 출력', 'href="/chat"',
  '이용약관', '개인정보 처리방침',
];
for (const text of required) {
  if (!html.includes(text)) throw new Error(`Pre-rendered home is missing required content: ${text}`);
}
if (html.includes('beta-notice-backdrop')) {
  throw new Error('A personal, browser-state popup must not be included in build HTML');
}
if (!fs.readFileSync(shellPath, 'utf8').includes(root)) {
  throw new Error('The non-home app shell must keep an empty root');
}
console.log(JSON.stringify({
  status: 'prerendered',
  html_bytes: Buffer.byteLength(html),
  shell_bytes: fs.statSync(shellPath).size,
  required_content_count: required.length,
  public_pages: Object.keys(PUBLIC_PAGE_META),
}));
