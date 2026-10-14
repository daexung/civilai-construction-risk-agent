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

const html = fs.readFileSync(indexPath, 'utf8');
const required = [
  '품셈이', '공사비 견적', '품셈 상담', '엑셀 출력', 'href="/chat"',
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
}));
