const { createProxyMiddleware } = require('http-proxy-middleware');

// package.json에 proxy가 없으면 CRA가 Host 검사를 하지 않으므로, 로컬 주소만 받도록 직접 검사한다(DNS rebinding 방지).
const LOCAL_HOST = /^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/i;

module.exports = function setupProxy(app) {
  app.use((req, res, next) => (LOCAL_HOST.test(req.headers.host || '') ? next() : res.status(403).end('Invalid Host header')));
  app.use('/api', createProxyMiddleware({
    target: process.env.CIVILAI_API_PROXY || 'http://localhost:8000',
    changeOrigin: true,
  }));
};
