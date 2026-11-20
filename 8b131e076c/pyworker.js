/* 文隐 TextVeil · 在浏览器后台线程里运行 Python 脱敏引擎（Pyodide），文档只在本机内存中处理 */
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.27.2/full/';
const V = '8b131e076c';
importScripts(PYODIDE + 'pyodide.js');
let py = null, W = null;
const say = (text) => postMessage({ type: 'log', text: String(text) });
const stage = (text) => postMessage({ type: 'stage', text: String(text) });

const persistSync = (populate) =>
  new Promise((resolve) => py.FS.syncfs(populate, () => resolve()));

const ready = (async () => {
  stage('正在加载 Python 运行环境…');
  py = await loadPyodide({ indexURL: PYODIDE });
  stage('正在加载文档解析组件…');
  const get = (p) => fetch(p + '?v=' + V).then((r) => {
    if (!r.ok) throw new Error('下载失败 ' + p + '（' + r.status + '）');
    return r.arrayBuffer();
  });
  const [, eng, libs] = await Promise.all([py.loadPackage(['lxml', 'pillow']), get('/engine.zip'), get('/libs.zip')]);
  py.unpackArchive(libs, 'zip', { extractDir: '/tv/lib' });
  py.unpackArchive(eng, 'zip', { extractDir: '/tv/app' });
  // 只有「设置」会存进浏览器本地（IndexedDB），文档和映射表不会
  try {
    py.FS.mkdirTree('/persist');
    py.FS.mount(py.FS.filesystems.IDBFS, {}, '/persist');
    await persistSync(true);
  } catch (e) { /* 隐私模式下可能不可用，忽略 */ }
  stage('正在启动脱敏引擎…');
  py.globals.set('tv_emit', say);
  py.runPython('import sys\nsys.path[:0] = ["/tv/app", "/tv/lib"]\nimport web_api as W\nW.make_api(tv_emit)');
  W = py.globals.get('W');
  postMessage({ type: 'ready' });
})().catch((e) => {
  postMessage({ type: 'fatal', error: String((e && e.message) || e) });
  throw e;
});

const SAVES = new Set(['save_settings', 'reset_settings', 'apply_preset', 'add_keyword_and_rescan', 'start_session', 'apply']);

function readOut(infoJson, transfer) {
  const info = JSON.parse(infoJson);
  const d = py.FS.readFile(info.path);
  transfer.push(d.buffer);
  return { name: info.name, mime: info.mime, data: d.buffer };
}

onmessage = async (ev) => {
  const { id, cmd, args } = ev.data;
  try {
    await ready;
    let result;
    const transfer = [];
    if (cmd === 'call') {
      result = JSON.parse(W.call(args.name, JSON.stringify(args.args || [])));
      if (SAVES.has(args.name)) persistSync(false);
    } else if (cmd === 'upload') {
      const paths = JSON.parse(W.new_upload_dir(JSON.stringify(args.files.map((f) => f.name))));
      args.files.forEach((f, i) => py.FS.writeFile(paths[i], new Uint8Array(f.data)));
      result = { paths };
    } else if (cmd === 'download') {
      result = readOut(W.prepare_download(args.kind, args.tok), transfer);
    } else if (cmd === 'file') {
      result = readOut(W.file_info(args.path), transfer);
    } else {
      throw new Error('未知命令 ' + cmd);
    }
    postMessage({ type: 'result', id, result }, transfer);
  } catch (e) {
    postMessage({ type: 'error', id, error: String((e && e.message) || e) });
  }
};
