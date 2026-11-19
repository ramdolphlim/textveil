# -*- coding: utf-8 -*-
"""文隐 TextVeil · 生成网页版（web/dist）。

网页版和桌面版共用同一套界面（desktop/ui）和脱敏引擎（textveil/）：
  * 界面：复制 desktop/ui，按下面 PATCHES 做少量替换（下载改成浏览器下载、去掉 PDF 和本机文件夹相关设置）
  * 引擎：textveil/ + desktop/textveil_desktop.py + web/web_api.py 打成 engine.zip，在浏览器里用 Pyodide 运行
  * 依赖：python-docx / python-pptx / openpyxl 等纯 Python 库打成 libs.zip，和页面一起由自己的域名提供
    （lxml、Pillow 由 Pyodide 官方 CDN 提供）

用法：
  python web/build_web.py                      # 自动用 pip download 下载依赖
  python web/build_web.py --site-packages DIR  # 离线：从已有的虚拟环境 site-packages 取依赖
"""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI = os.path.join(ROOT, "desktop", "ui")
DIST = os.path.join(HERE, "dist")

# 网页版用到的纯 Python 依赖（版本固定，便于复现）
PURE_LIBS = {
    "python-docx==1.2.0": ["docx"],
    "python-pptx==1.0.2": ["pptx"],
    "openpyxl==3.1.5": ["openpyxl"],
    "et-xmlfile==2.0.0": ["et_xmlfile"],
    "XlsxWriter==3.3.1": ["xlsxwriter"],
    "typing_extensions==4.16.0": ["typing_extensions.py"],
}

# (文件, 原文, 替换, 期望出现次数)
PATCHES = [
    ("app.js", "name: f.name, data_b64", "name: f.webkitRelativePath || f.name, data_b64", 1),
    ("app.js",
     "const v = await ask('输入文件夹路径', '浏览器模式下请输入本机文件夹完整路径（支持 Word / Excel / PPT / PDF / MD）', '');\n      if (v) startSession([v]);\n      return;",
     "$('f-dir').value = '';\n      $('f-dir').click();\n      return;", 1),
    ("app.js", "$('f-upload').onchange = async (e) => {", "$('f-upload').onchange = $('f-dir').onchange = async (e) => {", 1),
    ("app.js", "window.location.href = '/download/' + S.result.download_token", "TV.download('download', S.result.download_token)", 1),
    ("app.js", "window.location.href = '/download/' + S.rsResult.download_token", "TV.download('download', S.rsResult.download_token)", 1),
    ("app.js", "window.open('/report/' + S.result.report_token, '_blank')", "TV.download('report', S.result.report_token)", 1),
    ("app.js", "window.location.href = '/mapping/' + S.result.mapping_token", "TV.download('mapping', S.result.mapping_token)", 1),
    ("app.js", "toast('已导出映射表：' + p);", "TV.downloadPath(p);\n        toast('已导出映射表');", 1),
    ("app.js", "$('v-set').innerHTML = h;", "$('v-set').innerHTML = h;\n    TV.trimSettings($('v-set'));", 1),
    ("app.js", ": '输出到原文件旁';", ": '处理后下载到本机';", 1),
    ("app.js", "</span> 5 种格式就绪'", "</span> 4 种格式就绪（PDF 用桌面版）'", 1),
    ("app.js", " + sep +\n        '<button type=\"button\" data-set=\"1\">监视文件夹 ' + (s.watch_enabled && s.watch_dir ? '开' : '关') + '</button>';", ";", 1),
    ("app.js",
     "'⚠ 脱敏报告与映射表含原文，仅保存在本地「' + (s.report_dir || '').split(/[\\\\/]/).slice(-1)[0] + '」，切勿随文档外发'",
     "'⚠ 脱敏报告与映射表含原文，只在本页内存中，刷新即清除；下载后请妥善保管，切勿随文档外发'", 1),
    ("app.js", "'已保存至原文件旁「脱敏输出」文件夹'", "'点击下方按钮下载到本机'", 1),
    ("app.js", "toast('初始化失败，请确认后台服务已启动');", "toast('脱敏引擎加载失败，请刷新页面重试');", 1),
    ("index.html", '<link rel="stylesheet" href="app.css">', '<link rel="stylesheet" href="/app.css?v=__V__">\n<meta name="description" content="文隐 TextVeil：Word / Excel / PPT / Markdown 文档信息脱敏，在浏览器本地处理，文件不上传。">', 1),
    ("index.html", '<link rel="icon" href="favicon.svg" type="image/svg+xml">', '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n<link rel="apple-touch-icon" href="/icon.png">', 1),
    ("index.html", '<script src="app.js"></script>', '<script src="/tvweb.js?v=__V__"></script>\n<script src="/app.js?v=__V__"></script>', 1),
    ("index.html", '<p class="lead">本地离线处理，不联网、不上传 · 仅留存在这台电脑上</p>',
     '<p class="lead">在浏览器本地处理，文档不上传 · PDF 请用 <a href="https://github.com/peter804762649-ux/textveil/releases/latest" target="_blank" rel="noopener">桌面版</a></p>', 1),
    ("index.html", "<span>PDF</span>", "", 1),
    ("index.html", 'accept=".docx,.xlsx,.xlsm,.pptx,.pdf,.md,.markdown,.txt"', 'accept=".docx,.xlsx,.xlsm,.pptx,.md,.markdown,.txt"', 2),
    ("index.html", '<input type="file" id="f-upload"', '<input type="file" id="f-dir" webkitdirectory multiple hidden>\n    <input type="file" id="f-upload"', 1),
    ("index.html", '<footer class="foot" id="foot"></footer>',
     '<footer class="foot" id="foot"></footer>\n<a class="tv-gh" href="https://github.com/peter804762649-ux/textveil" target="_blank" rel="noopener">开源 · GitHub</a>', 1),
]

WEB_CSS = """
/* ---- 网页版附加样式 ---- */
.lead a { color: inherit; text-underline-offset: 3px; }
.tv-cover { position: fixed; inset: 0; z-index: 90; display: flex; align-items: center; justify-content: center; background: var(--paper); }
.tv-cover-box { display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center; color: var(--ink); max-width: 420px; padding: 24px; }
.tv-cover-box span { color: var(--muted); font-size: 13px; }
.tv-cover-box a { color: var(--accent); }
.tv-spin { width: 34px; height: 34px; border-radius: 50%; border: 3px solid var(--track); border-top-color: var(--accent); animation: tvrot 1s linear infinite; margin-bottom: 6px; }
@keyframes tvrot { to { transform: rotate(360deg); } }
.tv-note { position: fixed; left: 50%; top: 64px; transform: translateX(-50%); z-index: 80; max-width: min(560px, 92vw); padding: 10px 38px 10px 14px; border-radius: 10px;
  background: var(--warn-bg); color: var(--warn-ink); font-size: 13px; line-height: 1.5; box-shadow: 0 6px 24px rgba(0,0,0,.12); }
.tv-note a { color: inherit; font-weight: 600; }
.tv-note button { position: absolute; right: 8px; top: 6px; border: 0; background: transparent; color: inherit; font-size: 16px; cursor: pointer; }
.tv-gh { position: fixed; left: 16px; bottom: 12px; font-size: 12px; color: var(--muted); text-decoration: none; }
.tv-gh:hover { color: var(--ink); }
.tv-webinfo small a { color: var(--accent); }
"""


def _ensure_libs(site_packages=None):
    """返回一个目录，里面是 PURE_LIBS 需要的包。"""
    if site_packages:
        return site_packages
    tmp = tempfile.mkdtemp(prefix="tv_libs_")
    whl = os.path.join(tmp, "whl")
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                           "--python-version", "3.12", "-d", whl, *PURE_LIBS.keys()])
    out = os.path.join(tmp, "site")
    for w in os.listdir(whl):
        with zipfile.ZipFile(os.path.join(whl, w)) as z:
            z.extractall(out)
    return out


def _zip_tree(entries):
    """entries: [(磁盘路径, zip 内路径)]，目录递归，跳过缓存和测试。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arc in entries:
            if os.path.isfile(src):
                zf.write(src, arc)
                continue
            for d, dirs, files in os.walk(src):
                dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", "tests"))
                for f in sorted(files):
                    if f.endswith((".pyc", ".pyi")):
                        continue
                    p = os.path.join(d, f)
                    zf.write(p, os.path.join(arc, os.path.relpath(p, src)))
    return buf.getvalue()


def build(site_packages=None):
    shutil.rmtree(DIST, ignore_errors=True)
    os.makedirs(DIST)
    files = {}

    files["engine.zip"] = _zip_tree([
        (os.path.join(ROOT, "textveil"), "textveil"),
        (os.path.join(ROOT, "desktop", "textveil_desktop.py"), "textveil_desktop.py"),
        (os.path.join(HERE, "web_api.py"), "web_api.py"),
    ])
    sp = _ensure_libs(site_packages)
    lib_entries = []
    for names in PURE_LIBS.values():
        for n in names:
            p = os.path.join(sp, n)
            if not os.path.exists(p):
                raise SystemExit("缺少依赖 %s（在 %s 里没有找到）" % (n, sp))
            lib_entries.append((p, n))
    files["libs.zip"] = _zip_tree(lib_entries)

    text = {}
    for n in ("index.html", "app.js", "app.css"):
        with open(os.path.join(UI, n), encoding="utf-8") as f:
            text[n] = f.read()
    for fn, old, new, cnt in PATCHES:
        got = text[fn].count(old)
        if got != cnt:
            raise SystemExit("界面补丁对不上（%s 里出现 %d 次，应为 %d 次）：%s" % (fn, got, cnt, old[:60]))
        text[fn] = text[fn].replace(old, new)
    text["app.css"] += WEB_CSS
    for n in ("tvweb.js", "pyworker.js"):
        with open(os.path.join(HERE, "src", n), encoding="utf-8") as f:
            text[n] = f.read()
    text["robots.txt"] = "User-agent: *\nAllow: /\n"
    with open(os.path.join(ROOT, "assets", "logo", "favicon.svg"), encoding="utf-8") as f:
        text["favicon.svg"] = f.read()
    with open(os.path.join(ROOT, "desktop", "assets", "icon.png"), "rb") as f:
        files["icon.png"] = f.read()

    h = hashlib.sha256()
    for k in sorted(files):
        h.update(files[k])
    for k in sorted(text):
        h.update(text[k].encode("utf-8"))
    ver = h.hexdigest()[:10]
    for k in ("index.html", "tvweb.js", "pyworker.js"):
        text[k] = text[k].replace("__V__", ver)

    for k, v in text.items():
        with open(os.path.join(DIST, k), "w", encoding="utf-8") as f:
            f.write(v)
    for k, v in files.items():
        with open(os.path.join(DIST, k), "wb") as f:
            f.write(v)
    with open(os.path.join(DIST, "VERSION"), "w") as f:
        f.write(ver + "\n")
    for k in sorted(os.listdir(DIST)):
        print("%-12s %8d bytes" % (k, os.path.getsize(os.path.join(DIST, k))))
    print("version", ver)
    return ver


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-packages", help="从这个目录取纯 Python 依赖（离线构建）")
    build(ap.parse_args().site_packages)
