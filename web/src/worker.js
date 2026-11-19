// 文隐 TextVeil · Cloudflare Worker（textveil.limch.cc）
// 只提供静态页面：文件来自 GitHub 仓库的 site 分支（由 GitHub Actions 自动构建发布），经 Cloudflare 缓存后从本域名返回。
// 文档处理全部在用户浏览器里完成，这个 Worker 收不到、也不转发任何文档。
const ORIGIN = 'https://raw.githubusercontent.com/peter804762649-ux/textveil/site/';
const T = {
  html: 'text/html; charset=utf-8', js: 'text/javascript; charset=utf-8', css: 'text/css; charset=utf-8',
  svg: 'image/svg+xml', png: 'image/png', zip: 'application/zip', txt: 'text/plain; charset=utf-8'
};
// 页面入口（根目录，短缓存）
const ROOT_FILES = { '/': 'index.html', '/index.html': 'index.html', '/favicon.svg': 'favicon.svg', '/icon.png': 'icon.png', '/robots.txt': 'robots.txt' };
// 带版本号的资源：/app.js?v=<版本> → site/<版本>/app.js（内容不可变，长缓存）
const VERSIONED = new Set(['app.js', 'app.css', 'tvweb.js', 'pyworker.js', 'engine.zip', 'libs.zip', 'favicon.svg', 'icon.png']);
const CSP = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-eval' 'wasm-unsafe-eval'; " +
  "worker-src 'self' blob:; connect-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'";
const typeOf = (name) => T[{ html: 'html', js: 'js', css: 'css', svg: 'svg', png: 'png', zip: 'zip' }[name.split('.').pop()] || 'txt'];

export default {
  async fetch(request) {
    if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
    const url = new URL(request.url);
    const name = url.pathname.slice(1);
    const v = url.searchParams.get('v') || '';
    let key, ttl, browserCache;
    if (/^[0-9a-f]{10}$/.test(v) && VERSIONED.has(name)) {
      key = v + '/' + name; ttl = 31536000; browserCache = 'public, max-age=31536000, immutable';
    } else if (ROOT_FILES[url.pathname]) {
      key = ROOT_FILES[url.pathname]; ttl = 60; browserCache = key === 'index.html' ? 'no-cache' : 'public, max-age=3600';
    } else {
      return new Response('Not found', { status: 404, headers: { 'content-type': T.txt } });
    }
    const up = await fetch(ORIGIN + key, { cf: { cacheTtl: ttl, cacheEverything: true } });
    if (!up.ok) return new Response(up.status === 404 ? 'Not found' : 'Service unavailable', { status: up.status === 404 ? 404 : 503, headers: { 'content-type': T.txt } });
    return new Response(request.method === 'HEAD' ? null : up.body, {
      headers: {
        'content-type': typeOf(key),
        'cache-control': browserCache,
        'content-security-policy': CSP,
        'x-content-type-options': 'nosniff',
        'referrer-policy': 'no-referrer',
        'permissions-policy': 'camera=(), microphone=(), geolocation=()',
        'cross-origin-opener-policy': 'same-origin'
      }
    });
  }
};
