/* 文隐 TextVeil 前端交互逻辑（支持原生 pywebview 与 --browser 浏览器双端无缝运行） */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));

  let native = false;
  const bridge = (name, ...args) => {
    if (native) return window.pywebview.api[name](...args);
    return fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    })
      .then((r) => r.json())
      .then((j) => {
        if (!j.ok) throw new Error(j.error);
        return j.result;
      });
  };
  const call = async (name, ...args) => {
    try {
      return await bridge(name, ...args);
    } catch (e) {
      toast(String((e && e.message) || e));
      throw e;
    }
  };

  // ---------- 图标与常量 ----------
  const OK_ICON =
    '<svg width="88" height="88" viewBox="0 0 96 96" aria-hidden="true"><circle class="ic-ok-bg" cx="48" cy="48" r="44"></circle><path class="ic-ok" d="M29 49 L42 62 L68 35" fill="none" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
  const WARN_ICON =
    '<svg width="88" height="88" viewBox="0 0 96 96" aria-hidden="true"><circle class="ic-warn-bg" cx="48" cy="48" r="44"></circle><path class="ic-warn" d="M48 26 V54 M48 68 V69" stroke-width="7" stroke-linecap="round"></path></svg>';
  const MOON =
    '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"></path></svg>';
  const SUN =
    '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.6"></circle><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path></svg>';

  const S = {
    st: null,
    seq: 0,
    view: 'drop',
    from: 'drop',
    terms: [],
    scan: null,
    result: null,
    tab: 'all',
    q: '',
    lastJob: null,
    busyKind: '',
    busyAt: 0,
    rsPaths: [],
    rsMapPath: '',
    rsBatchVal: '',
    rsResult: null,
  };

  const finderName = () => (S.st && S.st.platform === 'win' ? '资源管理器' : '访达');
  const currentMode = () => (S.st && S.st.settings && S.st.settings.mode) || 'placeholder';

  // ---------- Toast 与 对话框 ----------
  let toastTimer = 0;
  function toast(text) {
    const t = $('toast');
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.hidden = true;
    }, 4200);
  }

  function ask(title, text, value, placeholder) {
    return new Promise((resolve) => {
      $('md-title').textContent = title;
      $('md-text').textContent = text || '';
      const inp = $('md-input');
      inp.hidden = value === undefined;
      inp.value = value || '';
      inp.placeholder = placeholder || '';
      $('modal').hidden = false;
      setTimeout(() => (value === undefined ? $('md-ok') : inp).focus(), 30);
      const done = (ok) => {
        $('modal').hidden = true;
        $('md-ok').onclick = $('md-cancel').onclick = inp.onkeydown = null;
        resolve(ok ? (value === undefined ? true : inp.value.trim()) : null);
      };
      $('md-ok').onclick = () => done(true);
      $('md-cancel').onclick = () => done(false);
      inp.onkeydown = (e) => {
        if (e.key === 'Enter') done(true);
        if (e.key === 'Escape') done(false);
      };
    });
  }

  // ---------- 明暗主题 ----------
  const sysDark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const curTheme = () => document.documentElement.dataset.theme || (sysDark && sysDark.matches ? 'dark' : 'light');
  function paintTheme() {
    const dark = curTheme() === 'dark';
    const b = $('b-theme');
    b.innerHTML = dark ? SUN : MOON;
    const lbl = dark ? '切换到 Mole 羊皮纸日间模式' : '切换到 Mole 终端黑夜模式';
    b.setAttribute('aria-label', lbl);
    b.title = lbl;
  }
  function setTheme(t) {
    if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
    paintTheme();
  }
  if (sysDark && sysDark.addEventListener) sysDark.addEventListener('change', paintTheme);

  // ---------- 视图路由 ----------
  const VIEWS = ['drop', 'busy', 'scan', 'review', 'done', 'restore', 'set'];
  function show(v) {
    if (v === 'set' && S.view !== 'set') S.from = S.view === 'busy' ? 'drop' : S.view;
    S.view = v;
    if (v === 'busy') S.busyAt = Date.now();
    VIEWS.forEach((k) => {
      $('v-' + k).hidden = k !== v;
    });
    const back = { scan: '‹ 重新选择', review: '‹ 返回汇总', done: '', set: '‹ 完成' }[v];
    $('b-back').hidden = !back;
    $('b-back').textContent = back || '';
    $('brand-mini').hidden = Boolean(back);
    $('nav-seg').hidden = v !== 'drop' && v !== 'restore';
    document.querySelectorAll('#nav-seg button').forEach((btn) => {
      btn.setAttribute('aria-pressed', String(btn.dataset.nav === (v === 'restore' ? 'restore' : 'drop')));
    });
    $('b-gear').hidden = v === 'set' || v === 'busy';
    syncModeButtons();
    renderFoot();
  }

  function goBack() {
    if (S.view === 'set') show(S.from || 'drop');
    else if (S.view === 'review') show('scan');
    else if (S.view === 'scan' || S.view === 'done') show('drop');
  }

  function syncModeButtons() {
    const mode = currentMode();
    ['drop-mode', 'scan-mode', 'rv-mode'].forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.querySelectorAll('button[data-mode]').forEach((btn) => {
        btn.setAttribute('aria-pressed', String(btn.dataset.mode === mode));
      });
    });
  }

  async function switchMode(newMode) {
    if (!S.st || currentMode() === newMode) return;
    S.st.settings.mode = newMode;
    syncModeButtons();
    // 同步未手工编辑过的条目的替换显示
    S.terms.forEach((t) => {
      if (!t.edited && !t.custom_replace) {
        t.replace = newMode === 'placeholder' ? t.placeholder_replace : t.mask_replace;
      }
    });
    if (S.view === 'review') renderReview();
    renderFoot();
    try {
      S.st = await bridge('save_settings', { mode: newMode });
    } catch (e) {}
  }

  function renderFoot() {
    const f = $('foot');
    const s = S.st ? S.st.settings : null;
    if (!s) {
      f.innerHTML = '';
      return;
    }
    const sep = '<span class="s">·</span>';
    if (S.view === 'drop' || S.view === 'restore') {
      const pName = ((S.st.presets || []).find((x) => x[0] === s.preset) || [0, '自定义规则'])[1];
      const mName = currentMode() === 'placeholder' ? '可逆占位符' : '掩码遮蔽';
      const outName = s.output_mode === 'fixed' && s.output_dir ? '输出到 ' + s.output_dir.split(/[\\/]/).pop() : '输出到原文件旁';
      const ready = S.st.env && S.st.env.all_ready;
      f.innerHTML =
        '<button type="button" data-set="1">' + esc(pName) + '</button>' + sep +
        '<button type="button" data-set="1">' + esc(mName) + '</button>' + sep +
        '<button type="button" data-set="1">' + esc(outName) + '</button>' + sep +
        '<button type="button" data-set="1">' + (ready ? '<span class="dot">●</span> 5 种格式就绪' : '<span class="dot bad">●</span> 检查格式引擎') + '</button>' + sep +
        '<button type="button" data-set="1">监视文件夹 ' + (s.watch_enabled && s.watch_dir ? '开' : '关') + '</button>';
    } else if (S.view === 'scan' && S.scan) {
      const fmts = Object.entries(S.scan.format_counts || {}).map(([k, v]) => k + '×' + v).join(' ');
      f.textContent = fmts + (s.reuse_mapping ? ' · 跨批次复用同一代号' : '');
    } else if (S.view === 'done') {
      f.textContent = '⚠ 脱敏报告与映射表含原文，仅保存在本地「' + (s.report_dir || '').split(/[\\/]/).slice(-1)[0] + '」，切勿随文档外发';
    } else {
      f.innerHTML = '';
    }
  }

  // ---------- 文件上传（浏览器模式） & 选文件 ----------
  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const res = String(fr.result || '');
        const idx = res.indexOf(',');
        resolve(idx >= 0 ? res.slice(idx + 1) : res);
      };
      fr.onerror = reject;
      fr.readAsDataURL(file);
    });
  }

  async function uploadBrowserFiles(fileList) {
    const arr = Array.from(fileList || []);
    if (!arr.length) return [];
    const payload = [];
    for (const f of arr) {
      payload.push({ name: f.name, data_b64: await fileToBase64(f) });
    }
    const resp = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: payload }),
    }).then((r) => r.json());
    if (!resp.ok) throw new Error(resp.error || '上传失败');
    return resp.result.paths || [];
  }

  async function pick(folder) {
    if (native) {
      const r = await call(folder ? 'pick_folder' : 'pick_files');
      const paths = r ? (Array.isArray(r) ? r : [r]) : [];
      if (paths.length) startSession(paths);
      return;
    }
    if (folder) {
      const v = await ask('输入文件夹路径', '浏览器模式下请输入本机文件夹完整路径（支持 Word / Excel / PPT / PDF / MD）', '');
      if (v) startSession([v]);
      return;
    }
    $('f-upload').value = '';
    $('f-upload').click();
  }

  async function startSession(paths) {
    S.busyKind = 'scan';
    $('busy-title').textContent = '正在扫描敏感信息';
    $('busy-line').textContent = '➤ 正在解析文档结构与元数据…';
    show('busy');
    try {
      S.st = await bridge('start_session', paths);
    } catch (e) {
      toast(String((e && e.message) || e));
      show('drop');
    }
  }

  // ---------- ② 扫描结果渲染 ----------
  function renderScan() {
    const T = S.terms;
    const sc = S.scan;
    const total = T.reduce((a, t) => a + t.count, 0);
    const mt = sc.meta_totals || {};
    const hiddenSum = (mt.meta_count || 0) + (mt.comment_count || 0) + (mt.revision_count || 0) + (mt.hidden_sheet_count || 0);

    $('sc-total').textContent = total;
    $('sc-sub').textContent = total
      ? '处敏感内容，分布在 ' + sc.files + ' 份文档中（共 ' + T.length + ' 项去重词条）'
      : '未检出正文敏感词，可继续清理文档隐藏属性';
    const fmts = Object.entries(sc.format_counts || {}).map(([k, v]) => k + ' ' + v).join(' · ');
    $('sc-meta').textContent = '用时 ' + (sc.seconds || 0) + 's · ' + fmts;

    const groups = S.st.cat_groups || [];
    const sums = groups
      .map(([, name, cats]) => [name, T.filter((t) => cats.includes(t.cat)).reduce((a, t) => a + t.count, 0)])
      .filter((x) => x[1] > 0);
    const maxV = Math.max(1, ...sums.map((x) => x[1]));
    let h = sums
      .map(
        ([n, c]) =>
          '<div class="bar"><span>' + esc(n) + '</span><div class="tr"><i style="width:' +
          Math.max(4, Math.round((c / maxV) * 100)) +
          '%"></i></div><span class="n">' + c + ' 处</span></div>'
      )
      .join('');

    if (hiddenSum > 0) {
      const parts = [];
      if (mt.meta_count) parts.push('属性 ' + mt.meta_count);
      if (mt.comment_count) parts.push('批注 ' + mt.comment_count);
      if (mt.revision_count) parts.push('修订 ' + mt.revision_count);
      if (mt.hidden_sheet_count) parts.push('隐藏表 ' + mt.hidden_sheet_count);
      h +=
        (h ? '<div class="sep"></div>' : '') +
        '<div class="bar"><span>隐藏属性与痕迹</span><span class="hint">' +
        esc(parts.join(' · ')) +
        '</span><span class="n">' + hiddenSum + ' 项</span></div>';
    }
    $('sc-bars').innerHTML = h;

    const warns = (sc.errors || []).slice(0, 3);
    (sc.file_stats || []).forEach((st) => {
      (st.notes || []).forEach((n) => warns.push(st.rel + '：' + n));
    });
    $('sc-warn').hidden = !warns.length;
    $('sc-warn').innerHTML = warns.slice(0, 4).map(esc).join('<br>');

    const okFiles = sc.files - (sc.errors || []).length;
    $('b-apply').textContent = total ? '脱敏 ' + okFiles + ' 份文档' : '清理 ' + okFiles + ' 份文档元数据';
    $('b-apply').disabled = okFiles <= 0;
    $('b-review').hidden = !T.length;
  }

  // ---------- ③ 逐项核对 ----------
  function groupOf(cat) {
    const groups = S.st.cat_groups || [];
    const g = groups.find((x) => x[2].includes(cat));
    return g ? g[0] : 'custom';
  }

  function visibleTerms() {
    return S.terms.filter((t) => {
      const inTab = S.tab === 'all' || groupOf(t.cat) === S.tab;
      if (!inTab) return false;
      if (!S.q) return true;
      return (
        t.term.toLowerCase().includes(S.q) ||
        String(t.replace || '').toLowerCase().includes(S.q) ||
        String(t.rule || '').toLowerCase().includes(S.q)
      );
    });
  }

  function renderReview(keepList) {
    const T = S.terms;
    const groups = S.st.cat_groups || [];
    $('rv-title').textContent = '核对 ' + T.reduce((a, t) => a + t.count, 0) + ' 处敏感信息';
    const tabs = [['all', '全部', T.length]].concat(
      groups.map(([gk, gn, cats]) => [gk, gn, T.filter((t) => cats.includes(t.cat)).length])
    );
    $('rv-tabs').innerHTML = tabs
      .filter((x) => x[0] === 'all' || x[2] > 0)
      .map(([k, n, c]) => '<button type="button" data-tab="' + k + '" aria-pressed="' + (S.tab === k) + '">' + esc(n) + ' ' + c + '</button>')
      .join('');

    if (!keepList) {
      const V = visibleTerms();
      $('rv-list').innerHTML = V.length
        ? V.map((t) => {
            const i = T.indexOf(t);
            const nf = (t.files || []).length;
            const infoTag = esc(t.cat_name || t.cat) + ' · ' + esc(t.rule) + ' · ' + (nf > 1 ? nf + ' 文档' : t.count + ' 处');
            return (
              '<label class="row' + (t.enabled ? '' : ' off') + '">' +
              '<input type="checkbox" data-en="' + i + '"' + (t.enabled ? ' checked' : '') + ' aria-label="替换 ' + esc(t.term) + '">' +
              '<span class="t" title="' + esc(t.term) + '">' + esc(t.term) +
              (t.samples && t.samples[0] && t.samples[0] !== t.term ? '<small>' + esc(t.samples[0].slice(0, 32)) + '</small>' : '') +
              '</span>' +
              '<span class="code">→<input type="text" data-rep="' + i + '" value="' + esc(t.enabled ? t.replace : '保留原文') + '"' + (t.enabled ? '' : ' disabled') + '></span>' +
              '<span class="why" title="' + infoTag + '">' + infoTag + '</span>' +
              '</label>'
            );
          }).join('')
        : '<div class="empty">没有符合条件的敏感条目</div>';
    }

    const on = T.filter((t) => t.enabled);
    $('rv-sum').textContent = '启用 ' + on.length + ' 项（共 ' + on.reduce((a, t) => a + t.count, 0) + ' 处）· 保留 ' + (T.length - on.length) + ' 项';
    $('b-apply2').textContent = $('b-apply').textContent;
  }

  // ---------- 执行脱敏 ----------
  async function apply() {
    const d = {};
    S.terms.forEach((t) => {
      d[t.term] = { enabled: t.enabled, replace: t.replace, edited: !!t.edited };
    });
    S.busyKind = 'apply';
    $('busy-title').textContent = '正在脱敏并校验';
    $('busy-line').textContent = '➤ 正在写回脱敏内容与物理校验…';
    show('busy');
    try {
      await bridge('apply', d, currentMode(), S.st.settings.pdf_style);
    } catch (e) {
      toast(String((e && e.message) || e));
      show('scan');
    }
  }

  // ---------- ④ 完成渲染 ----------
  function renderDone() {
    const R = S.result;
    const F = R.files || [];
    const bad = F.filter((f) => f.error || !f.structure_ok || (f.residual && f.residual.length));
    const allOk = bad.length === 0;
    $('dn-icon').innerHTML = allOk ? OK_ICON : WARN_ICON;
    const okN = F.length - bad.length;
    $('dn-title').textContent = allOk ? F.length + ' 份文档已安全脱敏' : okN + ' 份已完成，' + bad.length + ' 份需复查';

    const s = S.st.settings;
    $('dn-sub').textContent =
      (R.mode === 'placeholder' ? '可逆占位符模式 · ' : '不可逆掩码模式 · ') +
      (s.output_mode === 'fixed' && s.output_dir ? '已保存至 ' + s.output_dir : '已保存至原文件旁「脱敏输出」文件夹');

    const totalRep = F.reduce((a, f) => a + (f.changes || 0), 0);
    const removedSet = new Set();
    F.forEach((f) => (f.removed || []).forEach((x) => removedSet.add(x)));
    const structOk = F.filter((f) => f.structure_ok).length;
    const resCnt = F.reduce((a, f) => a + (f.residual ? f.residual.length : 0), 0);

    const row = (cls, mark, label, val) =>
      '<div class="' + cls + '"><span><span class="' + (cls || 'g') + '">' + mark + '</span>&nbsp; ' + esc(label) + '</span><span>' + esc(val) + '</span></div>';

    let h = row('', '✓', '脱敏替换', totalRep + ' 处');
    if (removedSet.size) h += row('', '✓', '清理元数据与痕迹', removedSet.size + ' 类');
    h += structOk === F.length
      ? row('', '✓', '文档结构与格式校验', structOk + ' / ' + F.length)
      : row('b', '✗', '结构校验异常', (F.length - structOk) + ' 份');
    h += resCnt === 0
      ? row('', '✓', '复查敏感原文残留', '0 处')
      : row('b', '✗', '检测到残留敏感原文', resCnt + ' 处');
    $('dn-checks').innerHTML = h;

    const iss = [];
    F.forEach((f) => {
      const nm = f.rel;
      if (f.error) iss.push(nm + '：' + f.error);
      else if (!f.structure_ok) iss.push(nm + '：' + f.structure_msg);
      if (f.residual && f.residual.length) iss.push(nm + ' 残留原文：' + f.residual.join('、'));
      (f.notes || []).forEach((n) => iss.push(nm + '：' + n));
    });
    $('dn-issues').hidden = !iss.length;
    $('dn-issues').innerHTML = iss.map((x) => '<li>' + esc(x) + '</li>').join('');

    $('b-show').textContent = '在' + finderName() + '中显示';
    $('b-show').hidden = !native;
    $('b-show').disabled = !F.some((f) => f.output);
    $('b-download').hidden = native || !R.download_token;
    $('b-gorestore').hidden = R.mode !== 'placeholder';
  }

  // ---------- ⑤ 还原页 ----------
  async function renderRestoreView() {
    S.rsResult = null;
    $('rs-done').hidden = true;
    $('rs-show').hidden = true;
    $('rs-dl').hidden = true;
    const batches = await call('list_saved_mappings');
    const sel = $('rs-batch-sel');
    if (batches && batches.length) {
      sel.innerHTML = batches
        .map((b) => '<option value="batch:' + esc(b.id) + '">' + esc(b.name) + '（' + b.count + ' 条映射 · ' + esc(b.created) + '）</option>')
        .join('');
      if (!S.rsMapPath) S.rsBatchVal = sel.value;
    } else {
      sel.innerHTML = '<option value="">暂无本地批次记录，请导入映射表.json</option>';
      if (!S.rsMapPath) S.rsBatchVal = '';
    }
    await updateRestorePreview();
  }

  async function updateRestorePreview() {
    $('rs-files').textContent = S.rsPaths.length
      ? S.rsPaths.map((p) => p.split(/[\\/]/).pop()).join('、')
      : '尚未选择文档（可点击按钮或直接拖入）';
    $('rs-mapname').textContent = S.rsMapPath
      ? '已选外部映射表：' + S.rsMapPath.split(/[\\/]/).pop()
      : S.rsBatchVal
      ? '使用所选批次记录'
      : '请选择一个批次或映射表.json';

    const mapSrc = S.rsMapPath || S.rsBatchVal;
    const ready = S.rsPaths.length > 0 && Boolean(mapSrc);
    $('rs-run').disabled = !ready;
    if (!ready) {
      $('rs-preview').hidden = true;
      return;
    }
    try {
      const pv = await bridge('restore_preview', S.rsPaths, mapSrc);
      const warns = pv.warnings || [];
      const pairs = (pv.sample_pairs || []).slice(0, 4).map((x) => esc(x.code) + ' → ' + esc(x.orig)).join('； ');
      $('rs-preview').hidden = false;
      $('rs-preview').innerHTML =
        '<div>✓ 已识别 ' + pv.files.length + ' 份文档 · 可用可逆映射 ' + pv.inv_count + ' 条</div>' +
        (pairs ? '<div class="muted">示例：' + pairs + '</div>' : '') +
        (warns.length ? '<div style="color:var(--warn)">◎ ' + warns.map(esc).join('<br>◎ ') + '</div>' : '');
    } catch (e) {
      $('rs-preview').hidden = true;
    }
  }

  async function runRestore() {
    const mapSrc = S.rsMapPath || S.rsBatchVal;
    if (!S.rsPaths.length || !mapSrc) return;
    S.busyKind = 'restore';
    $('busy-title').textContent = '正在还原文档';
    $('busy-line').textContent = '➤ 正在回填占位符并校验结构…';
    show('busy');
    try {
      await bridge('restore_apply', S.rsPaths, mapSrc);
    } catch (e) {
      toast(String((e && e.message) || e));
      show('restore');
    }
  }

  // ---------- 设置页 ----------
  function sw(id, on, dis) {
    return '<input type="checkbox" class="switch" id="' + id + '"' + (on ? ' checked' : '') + (dis ? ' disabled' : '') + '>';
  }

  function renderSettings() {
    const st = S.st;
    const s = st.settings;
    const open = new Set([...document.querySelectorAll('#v-set details[open]')].map((d) => d.id));
    const groups = {};
    st.options.forEach((o) => (groups[o[2]] = groups[o[2]] || []).push(o));
    const sel = (id, opts, v) =>
      '<select id="' + id + '">' +
      opts.map(([k, n]) => '<option value="' + esc(k) + '"' + (k === v ? ' selected' : '') + '>' + esc(n) + '</option>').join('') +
      '</select>';

    let h = '<h1>设置与规则</h1>';
    h += '<section><h2>脱敏预设</h2><div class="presets">' +
      (st.presets || []).map(([k, n, d]) =>
        '<button type="button" data-preset="' + k + '" aria-pressed="' + (s.preset === k) + '"><b>' + esc(n) + '</b><span>' + esc(d) + '</span></button>'
      ).join('') +
      '</div></section>';

    h += '<section class="rows">';
    h += '<div class="srow"><div class="l">默认脱敏模式<small>可逆占位符会生成映射表用于还原；掩码遮蔽不可逆</small></div><div class="r">' +
      sel('s-mode', [['placeholder', '可逆占位符'], ['mask', '掩码遮蔽']], s.mode) + '</div></div>';
    h += '<div class="srow"><div class="l">PDF 掩码模式样式<small>白底覆写保留自然版面；黑块涂黑彻底抹除文字并覆盖黑色遮挡条</small></div><div class="r">' +
      sel('s-pdfstyle', [['replace', '白底覆写掩码'], ['blackbox', '纯黑块涂黑']], s.pdf_style || 'replace') + '</div></div>';
    h += '<div class="srow"><div class="l">脱敏输出位置' +
      (s.output_mode === 'fixed' ? '<small class="mono">' + esc(s.output_dir || '尚未选择输出目录') + '</small>' : '<small>默认保存至原文件同目录的「脱敏输出」文件夹</small>') +
      '</div><div class="r">' +
      (s.output_mode === 'fixed' ? '<button type="button" class="btn" id="s-outdir">更改…</button>' : '') +
      sel('s-outmode', [['beside', '原文件旁「脱敏输出」'], ['fixed', '固定目录']], s.output_mode === 'fixed' ? 'fixed' : 'beside') +
      '</div></div>';
    h += '<label class="srow"><span class="l">跨批次复用同一个代号<small>同一人名、公司在后续批次中保持相同占位符编号</small></span>' + sw('s-reuse', s.reuse_mapping) + '</label>';
    h += '<div class="srow"><div class="l">监视文件夹自动脱敏<small class="mono">' +
      (s.watch_dir ? esc(s.watch_dir) + ' → ' + esc(s.watch_out_dir || '已脱敏') : '拖入或保存到该目录的文档将自动完成脱敏') +
      '</small></div><div class="r"><button type="button" class="btn" id="s-watchdir">' + (s.watch_dir ? '更改…' : '选择…') + '</button>' +
      sw('s-watch', s.watch_enabled && s.watch_dir, !s.watch_dir) + '</div></div>';
    h += '<label class="srow"><span class="l">完成后在' + finderName() + '中显示输出文件</span>' + sw('s-reveal', s.reveal_after) + '</label>';
    h += '</section>';

    h += '<section class="rows">';
    h += '<details id="d-rules"' + (open.has('d-rules') ? ' open' : '') + '><summary>四类敏感信息详细规则</summary><div class="dbody">' +
      Object.keys(groups).map((g) =>
        '<div class="optgroup">' + esc(g) + '</div>' +
        groups[g].map((o) => '<label class="opt"><input type="checkbox" data-o="' + o[0] + '"' + (s.options[o[0]] ? ' checked' : '') + '><span>' + esc(o[3]) + '</span></label>').join('')
      ).join('') +
      '</div></details>';

    h += '<details id="d-words"' + (open.has('d-words') ? ' open' : '') + '><summary>自定义敏感词与白名单<span class="muted" style="margin-left:auto;margin-right:10px;font-size:12px">' + (s.keywords || []).length + ' 个规则</span></summary><div class="dbody">' +
      '<div class="optgroup">自定义敏感词（每行一条，支持 原词=替换词 或 re:正则表达式）</div>' +
      '<textarea id="s-kw">' + esc((s.keywords || []).join('\n')) + '</textarea>' +
      '<div class="optgroup">白名单（命中这些词时永不脱敏）</div>' +
      '<textarea id="s-wl">' + esc((s.whitelist || []).join('\n')) + '</textarea>' +
      '</div></details>';

    h += '<details id="d-adv"' + (open.has('d-adv') ? ' open' : '') + '><summary>占位符格式、报告目录与引擎状态</summary><div class="dbody">' +
      '<div class="optgroup">可逆占位符模板（{n:02d} 表示两位编号）</div><div class="codes">' +
      Object.entries(st.cats).map(([k, n]) => '<label>' + esc(n) + '<input class="field mono" data-code="' + k + '" value="' + esc(s.pseudonyms[k] || '') + '"></label>').join('') +
      '</div>' +
      '<div class="srow"><div class="l">内部留存报告目录<small class="mono">' + esc(s.report_dir) + '</small></div><div class="r"><button type="button" class="btn" id="s-repdir">更改…</button></div></div>' +
      '<div class="srow"><div class="l">导出当前批次代号库<small>另存映射 JSON 以便归档或交接还原</small></div><div class="r"><button type="button" class="btn" id="s-export">导出</button></div></div>' +
      '<div class="srow"><div class="l muted" style="font-size:12px">' + esc(st.app) + ' v' + esc(st.version) + ' · PDF 字体: ' + esc(st.env.pdf_font_path) + '</div><div class="r"><button type="button" class="btn" id="s-reset">恢复默认</button></div></div>' +
      '</div></details>';
    h += '</section>';

    $('v-set').innerHTML = h;
  }

  async function savePart(part, rerender) {
    S.st = await call('save_settings', part);
    if (rerender !== false) renderSettings();
    renderFoot();
    syncModeButtons();
  }

  async function pickDirPrompt() {
    if (native) return await call('pick_folder');
    return await ask('选择文件夹', '浏览器模式下请输入文件夹完整路径', '');
  }

  // ---------- 轮询异步任务 ----------
  async function poll() {
    try {
      const p = await bridge('poll', S.seq);
      S.seq = p.seq;
      if (p.logs && p.logs.length) {
        $('busy-line').textContent = p.logs[p.logs.length - 1].text.trim();
      }
      const j = p.job;
      if (S.lastJob === null) {
        S.lastJob = j && j.status !== 'running' ? j.id + j.status : '';
      }
      if (j && j.status === 'running' && (j.kind === 'scan' || j.kind === 'apply' || j.kind === 'restore') && S.view !== 'busy') {
        S.busyKind = j.kind;
        $('busy-title').textContent = j.kind === 'scan' ? '正在扫描敏感信息' : j.kind === 'apply' ? '正在脱敏并校验' : '正在还原文档';
        show('busy');
      }
      if (j && j.status !== 'running' && S.lastJob !== j.id + j.status) {
        S.lastJob = j.id + j.status;
        if (j.status === 'error') {
          toast('处理出错：' + j.error);
          if (S.view === 'busy') show(j.kind === 'apply' ? 'scan' : j.kind === 'restore' ? 'restore' : 'drop');
        } else if (j.kind === 'scan') {
          S.scan = j.result;
          const mode = currentMode();
          S.terms = (j.result.terms || []).map((t) =>
            Object.assign({}, t, {
              edited: false,
              replace: t.custom_replace || (mode === 'placeholder' ? t.placeholder_replace : t.mask_replace),
            })
          );
          S.tab = 'all';
          S.q = '';
          $('rv-q').value = '';
          renderScan();
          show('scan');
        } else if (j.kind === 'apply') {
          S.result = j.result;
          renderDone();
          show('done');
        } else if (j.kind === 'restore') {
          S.rsResult = j.result;
          show('restore');
          const r = j.result;
          $('rs-done').hidden = false;
          $('rs-done').innerHTML =
            '<div style="color:var(--ok);font-weight:600">✓ 已还原 ' + r.ok + ' / ' + r.total + ' 份文档（用时 ' + r.seconds + 's）</div>' +
            (r.files || []).map((f) => '<div>↳ ' + esc(f.rel) + ' · 回填 ' + f.restored_count + ' 处' + (f.unmapped && f.unmapped.length ? ' · 未匹配: ' + esc(f.unmapped.join(',')) : '') + '</div>').join('');
          $('rs-show').hidden = !native;
          $('rs-dl').hidden = native || !r.download_token;
        } else if (j.kind === 'watch') {
          const r = j.result || {};
          toast('监视文件夹：已自动脱敏 ' + (r.ok || 0) + ' / ' + (r.total || 0) + ' 份文档');
        }
        S.st = await bridge('get_state');
      }
    } catch (e) {}
    setTimeout(poll, 500);
  }

  // ---------- 事件绑定 ----------
  function bind() {
    $('b-ring').onclick = () => pick(false);
    $('b-pick').onclick = () => pick(false);
    $('b-pickdir').onclick = () => pick(true);
    $('b-back').onclick = goBack;

    document.querySelectorAll('#nav-seg button').forEach((btn) => {
      btn.onclick = () => {
        if (btn.dataset.nav === 'restore') {
          show('restore');
          renderRestoreView();
        } else {
          show('drop');
        }
      };
    });

    $('b-theme').onclick = () => {
      const t = curTheme() === 'dark' ? 'light' : 'dark';
      setTheme(t);
      bridge('save_settings', { theme: t }).then((st) => { S.st = st; }).catch(() => {});
    };

    ['drop-mode', 'scan-mode', 'rv-mode'].forEach((id) => {
      $(id).onclick = (e) => {
        const b = e.target.closest('button[data-mode]');
        if (b) switchMode(b.dataset.mode);
      };
    });

    $('f-upload').onchange = async (e) => {
      try {
        const paths = await uploadBrowserFiles(e.target.files);
        if (paths.length) startSession(paths);
      } catch (err) {
        toast(String(err.message || err));
      }
    };

    // 浏览器文件拖拽上传支持（脱敏首页与还原页）
    document.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (S.view === 'drop') document.body.classList.add('dragging');
      if (S.view === 'restore') $('rs-dropzone').classList.add('dragover');
    });
    document.addEventListener('dragleave', (e) => {
      if (!e.relatedTarget) {
        document.body.classList.remove('dragging');
        $('rs-dropzone').classList.remove('dragover');
      }
    });
    document.addEventListener('drop', async (e) => {
      e.preventDefault();
      document.body.classList.remove('dragging');
      $('rs-dropzone').classList.remove('dragover');
      if (native) return; // pywebview 原生 drop handler 会直接拿绝对路径
      const files = e.dataTransfer && e.dataTransfer.files;
      if (!files || !files.length) return;
      try {
        const paths = await uploadBrowserFiles(files);
        if (S.view === 'restore') {
          S.rsPaths = paths;
          updateRestorePreview();
        } else if (S.view === 'drop') {
          startSession(paths);
        }
      } catch (err) {
        toast(String(err.message || err));
      }
    });

    $('b-gear').onclick = () => { renderSettings(); show('set'); };
    $('foot').onclick = (e) => {
      if (e.target.closest('[data-set]')) { renderSettings(); show('set'); }
    };

    $('b-apply').onclick = apply;
    $('b-apply2').onclick = apply;
    $('b-review').onclick = () => { renderReview(); show('review'); };

    $('b-addkw').onclick = async () => {
      const val = await ask('补充敏感词', '支持直接填词、原词=替换词，或 re:正则表达式。添加后将自动重扫当前文档。', '', '例如：核心项目代号 或 内部系统=某系统');
      if (!val) return;
      S.busyKind = 'scan';
      $('busy-title').textContent = '正在应用新规则重扫';
      show('busy');
      try {
        S.st = await bridge('add_keyword_and_rescan', val);
      } catch (err) {
        toast(String(err.message || err));
        show('review');
      }
    };

    $('rv-tabs').onclick = (e) => {
      const b = e.target.closest('[data-tab]');
      if (b) { S.tab = b.dataset.tab; renderReview(); }
    };
    $('rv-q').oninput = (e) => { S.q = e.target.value.trim().toLowerCase(); renderReview(); };
    $('rv-list').onchange = (e) => {
      const en = e.target.dataset.en;
      if (en !== undefined) {
        S.terms[+en].enabled = e.target.checked;
        renderReview();
      }
    };
    $('rv-list').oninput = (e) => {
      const r = e.target.dataset.rep;
      if (r !== undefined) {
        S.terms[+r].replace = e.target.value;
        S.terms[+r].edited = true;
      }
    };

    $('b-show').onclick = () => {
      const f = (S.result.files || []).find((x) => x.output);
      if (f) call('reveal', f.output);
    };
    $('b-download').onclick = () => {
      if (S.result && S.result.download_token) window.location.href = '/download/' + S.result.download_token;
    };
    $('b-report').onclick = () => {
      if (native) call('open_path', S.result.report_html);
      else if (S.result && S.result.report_token) window.open('/report/' + S.result.report_token, '_blank');
    };
    $('b-dlmap').onclick = () => {
      if (native) call('reveal', S.result.mapping_json);
      else if (S.result && S.result.mapping_token) window.location.href = '/mapping/' + S.result.mapping_token;
    };
    $('b-gorestore').onclick = () => {
      S.rsPaths = (S.result && S.result.files ? S.result.files.map((x) => x.output).filter(Boolean) : []);
      S.rsMapPath = (S.result && S.result.mapping_json) || '';
      show('restore');
      renderRestoreView();
    };
    $('b-again').onclick = () => show('drop');

    // 还原页绑定
    $('rs-pick').onclick = async () => {
      if (native) {
        const res = await call('pick_files');
        if (res && res.length) { S.rsPaths = res; updateRestorePreview(); }
      } else {
        $('rs-upload').value = '';
        $('rs-upload').click();
      }
    };
    $('rs-upload').onchange = async (e) => {
      try {
        const paths = await uploadBrowserFiles(e.target.files);
        if (paths.length) { S.rsPaths = paths; updateRestorePreview(); }
      } catch (err) { toast(String(err.message || err)); }
    };
    $('rs-batch-sel').onchange = (e) => {
      S.rsBatchVal = e.target.value;
      S.rsMapPath = '';
      updateRestorePreview();
    };
    $('rs-pickmap').onclick = async () => {
      if (native) {
        const p = await call('pick_mapping_file');
        if (p) { S.rsMapPath = p; updateRestorePreview(); }
      } else {
        $('rs-mapupload').value = '';
        $('rs-mapupload').click();
      }
    };
    $('rs-mapupload').onchange = async (e) => {
      try {
        const paths = await uploadBrowserFiles(e.target.files);
        if (paths.length) { S.rsMapPath = paths[0]; updateRestorePreview(); }
      } catch (err) { toast(String(err.message || err)); }
    };
    $('rs-run').onclick = runRestore;
    $('rs-show').onclick = () => {
      const f = S.rsResult && (S.rsResult.files || []).find((x) => x.output);
      if (f) call('reveal', f.output);
    };
    $('rs-dl').onclick = () => {
      if (S.rsResult && S.rsResult.download_token) window.location.href = '/download/' + S.rsResult.download_token;
    };

    // 设置页代理事件
    const set = $('v-set');
    set.onclick = async (e) => {
      const pb = e.target.closest('[data-preset]');
      if (pb) {
        S.st = await call('apply_preset', pb.dataset.preset);
        renderSettings();
        renderFoot();
        syncModeButtons();
        return;
      }
      const id = e.target.id;
      if (id === 's-outdir' || id === 's-repdir') {
        const d = await pickDirPrompt();
        if (d) savePart(id === 's-outdir' ? { output_dir: d, output_mode: 'fixed' } : { report_dir: d });
      } else if (id === 's-watchdir') {
        const d = await pickDirPrompt();
        if (d) savePart({ watch_dir: d, watch_enabled: true });
      } else if (id === 's-export') {
        const p = await call('export_mapping');
        toast('已导出映射表：' + p);
      } else if (id === 's-reset') {
        if (await ask('恢复默认设置', '所有开关和自定义规则将恢复为默认值。')) {
          S.st = await call('reset_settings');
          renderSettings();
          renderFoot();
        }
      }
    };

    set.onchange = async (e) => {
      const t = e.target;
      if (t.id === 's-mode') return savePart({ mode: t.value }, false);
      if (t.id === 's-pdfstyle') return savePart({ pdf_style: t.value }, false);
      if (t.id === 's-outmode') {
        if (t.value === 'fixed' && !S.st.settings.output_dir) {
          const d = await pickDirPrompt();
          if (!d) { renderSettings(); return; }
          return savePart({ output_mode: 'fixed', output_dir: d });
        }
        return savePart({ output_mode: t.value });
      }
      if (t.id === 's-reuse') return savePart({ reuse_mapping: t.checked }, false);
      if (t.id === 's-reveal') return savePart({ reveal_after: t.checked }, false);
      if (t.id === 's-watch') return savePart({ watch_enabled: t.checked });

      const o = t.dataset.o;
      if (o) {
        const opts = Object.assign({}, S.st.settings.options);
        opts[o] = t.checked;
        return savePart({ options: opts, preset: 'custom' });
      }
      if (t.id === 's-kw' || t.id === 's-wl') {
        const lines = t.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
        return savePart(t.id === 's-kw' ? { keywords: lines } : { whitelist: lines }, false);
      }
      const code = t.dataset.code;
      if (code) {
        const ps = Object.assign({}, S.st.settings.pseudonyms);
        ps[code] = t.value.trim() || S.st.defaults.pseudonyms[code];
        return savePart({ pseudonyms: ps }, false);
      }
    };
  }

  // ---------- 初始化 ----------
  async function init() {
    native = !!(window.pywebview && window.pywebview.api);
    bind();
    try {
      S.st = await bridge('get_state');
      setTheme((S.st.settings && S.st.settings.theme) || '');
      show('drop');
      poll();
    } catch (e) {
      paintTheme();
      toast('初始化失败，请确认后台服务已启动');
    }
  }

  if (window.pywebview && window.pywebview.api) init();
  else {
    window.addEventListener('pywebviewready', init, { once: true });
    setTimeout(() => { if (!S.st) init(); }, 180);
  }
})();
