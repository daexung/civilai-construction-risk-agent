const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function setupProxy(app) {
  app.use('/api', createProxyMiddleware({
    target: process.env.CIVILAI_API_PROXY || 'http://localhost:8000',
    changeOrigin: true,
  }));
};
