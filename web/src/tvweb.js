/* 文隐 TextVeil · 网页版桥接层：把界面的 /api/... 请求转给浏览器后台线程里的脱敏引擎，文档不离开本机 */
(function () {
  'use strict';
  const DESKTOP = 'https://github.com/ramdolphlim/textveil/releases/latest';
  const worker = new Worker('/pyworker.js?v=__V__');
  const pend = new Map();
  let seq = 0;

  // ---------- 加载遮罩 ----------
  const cover = document.createElement('div');
  cover.className = 'tv-cover';
  cover.innerHTML = '<div class="tv-cover-box"><div class="tv-spin"></div><b>正在准备脱敏引擎</b>' +
    '<span id="tv-stage">首次打开约需下载 15MB，之后浏览器会缓存</span></div>';
  const mount = () => document.body.appendChild(cover);
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);

  const note = (html, sticky) => {
    let n = document.getElementById('tv-note');
    if (!n) {
      n = document.createElement('div');
      n.id = 'tv-note';
      n.className = 'tv-note';
      document.body.appendChild(n);
    }
    n.innerHTML = html + '<button type="button" aria-label="关闭">×</button>';
    n.hidden = false;
    n.querySelector('button').onclick = () => { n.hidden = true; };
    clearTimeout(n._t);
    if (!sticky) n._t = setTimeout(() => { n.hidden = true; }, 7000);
  };

  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === 'log') {
      const bl = document.getElementById('busy-line');
      if (bl) bl.textContent = m.text.trim();
      return;
    }
    if (m.type === 'stage') {
      const s = document.getElementById('tv-stage');
      if (s) s.textContent = m.text;
      return;
    }
    if (m.type === 'ready') {
      cover.remove();
      return;
    }
    if (m.type === 'fatal') {
      cover.querySelector('.tv-cover-box').innerHTML = '<b>脱敏引擎加载失败</b><span>' +
        String(m.error).replace(/[<>&]/g, '') + '</span><span>请检查网络后刷新页面，或使用 <a href="' + DESKTOP + '" target="_blank" rel="noopener">桌面版</a></span>';
      return;
    }
    const p = pend.get(m.id);
    if (!p) return;
    pend.delete(m.id);
    if (m.type === 'error') p.reject(new Error(m.error));
    else p.resolve(m.result);
  };

  const rpc = (cmd, args, transfer) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pend.set(id, { resolve, reject });
      worker.postMessage({ id, cmd, args }, transfer || []);
    });

  const b64ToBuf = (b64) => {
    const bin = atob(b64 || '');
    const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u.buffer;
  };

  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    const u = String(url);
    if (!u.startsWith('/api/')) return realFetch(url, opts);
    const name = u.slice(5);
    let out;
    try {
      const body = opts && opts.body ? JSON.parse(opts.body) : [];
      if (name === 'upload') {
        const all = (body.files || []).filter((f) => !/(^|\/)(\.|~\$)/.test(f.name) && /\.(docx|xlsx|xlsm|pptx|pdf|md|markdown|txt|json)$/i.test(f.name));
        const pdf = all.filter((f) => /\.pdf$/i.test(f.name));
        const files = all.filter((f) => !/\.pdf$/i.test(f.name)).map((f) => ({ name: f.name, data: b64ToBuf(f.data_b64) }));
        if (pdf.length) {
          note('网页版暂不支持 PDF，已跳过 ' + pdf.length + ' 个 PDF。PDF 请用 <a href="' + DESKTOP + '" target="_blank" rel="noopener">桌面版（Mac / Windows）</a>', true);
        }
        if (!files.length) throw new Error(pdf.length ? '网页版暂不支持 PDF，请使用桌面版' : '没有可处理的文档');
        const r = await rpc('upload', { files }, files.map((f) => f.data));
        out = { ok: true, result: { paths: r.paths } };
      } else {
        out = await rpc('call', { name, args: body });
      }
    } catch (e) {
      out = { ok: false, error: String((e && e.message) || e) };
    }
    return new Response(JSON.stringify(out), { headers: { 'content-type': 'application/json' } });
  };

  const save = (r) => {
    const url = URL.createObjectURL(new Blob([r.data], { type: r.mime }));
    const a = document.createElement('a');
    a.href = url;
    a.download = r.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  const HIDE = ['s-outmode', 's-outdir', 's-watchdir', 's-reveal', 's-repdir', 's-pdfstyle'];

  window.TV = {
    web: true,
    async download(kind, tok) {
      // 报告在新标签页打开：先同步开窗，避免被浏览器拦截弹窗
      const win = kind === 'report' ? window.open('', '_blank') : null;
      try {
        const r = await rpc('download', { kind, tok });
        if (win) {
          win.location.href = URL.createObjectURL(new Blob([r.data], { type: r.mime }));
        } else save(r);
      } catch (e) {
        if (win) win.close();
        note('下载失败：' + String((e && e.message) || e).replace(/[<>&]/g, ''));
      }
    },
    async downloadPath(path) {
      try { save(await rpc('file', { path })); } catch (e) { note('导出失败：' + String((e && e.message) || e).replace(/[<>&]/g, '')); }
    },
    trimSettings(root) {
      HIDE.forEach((id) => {
        const el = root.querySelector('#' + id);
        const row = el && el.closest('.srow');
        if (row) row.remove();
      });
      root.querySelectorAll('.srow .l.muted').forEach((el) => {
        el.textContent = el.textContent.replace(/ · PDF 字体:.*$/, ' · 网页版');
      });
      const sec = root.querySelector('section.rows');
      if (sec && !root.querySelector('.tv-webinfo')) {
        const d = document.createElement('div');
        d.className = 'srow tv-webinfo';
        d.innerHTML = '<div class="l">网页版说明<small>文档在浏览器内存中处理，不会上传；刷新页面后批次和映射表即清除，需要还原请先下载「映射表.json」。PDF、监视文件夹等功能请用 <a href="' +
          DESKTOP + '" target="_blank" rel="noopener">桌面版</a></small></div>';
        sec.appendChild(d);
      }
    },
  };
})();
