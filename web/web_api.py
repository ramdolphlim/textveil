# -*- coding: utf-8 -*-
"""文隐 TextVeil · 网页版接口：在浏览器后台线程（Pyodide）里运行桌面版同一套 Api。

文件只存在于浏览器内存（Pyodide 的虚拟文件系统）里，不会上传。
与桌面版的区别：
  * 没有线程：扫描 / 脱敏 / 还原任务同步执行（本身就在 Web Worker 里，不会卡住页面）
  * 没有 PyMuPDF：网页版不处理 PDF，其余 4 种格式完全一致
  * 只在浏览器本地保存「设置」；批次与映射表只留在当前页面，刷新即清除（请下载 映射表.json 备用）
"""

import json
import os
import shutil
import sys
import threading
import time
import types
import uuid
import zipfile

# Pyodide 里不能创建子进程；桌面模块顶部 import subprocess，这里给一个空壳
try:
    import subprocess  # noqa: F401
except Exception:  # pragma: no cover - 仅浏览器
    sys.modules["subprocess"] = types.ModuleType("subprocess")

import textveil_desktop as D  # noqa: E402

ROOT = os.environ.get("TEXTVEIL_WEB_ROOT", "/tv")  # 浏览器里的虚拟目录；测试时可改到临时目录
UPLOADS = ROOT + "/uploads"
DOWNLOADS = ROOT + "/dl"
REPORTS = ROOT + "/reports"
PERSIST = os.environ.get("TEXTVEIL_WEB_PERSIST", "/persist")
KEEP_UPLOAD_SESSIONS = 3


class _InlineThread:
    """浏览器里没有线程：桌面版的后台监视线程直接不启动。"""

    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self):
        pass


D.reveal = lambda path: False  # 网页版没有「在访达中显示」
D.open_path = lambda path: False
D.threading = types.SimpleNamespace(RLock=threading.RLock, Event=threading.Event, Thread=_InlineThread, Lock=threading.Lock)


class WebApi(D.Api):
    def __init__(self, emit=None):
        self._emit = emit
        os.makedirs(PERSIST, exist_ok=True)
        super().__init__(state_path=os.path.join(PERSIST, "settings.json"))
        self.settings["report_dir"] = REPORTS
        self.settings["output_mode"] = "beside"
        self.settings["watch_enabled"] = False
        self.settings["reveal_after"] = False

    # 只把「设置」存进浏览器（IndexedDB）；批次里的映射表含原文，只留在内存
    def _save(self):
        s = dict(self.settings)
        for k in ("report_dir", "output_dir", "watch_dir", "watch_out_dir"):
            s.pop(k, None)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump({"settings": s}, f, ensure_ascii=False)

    def log(self, text: str):
        super().log(text)
        if self._emit:
            try:
                self._emit(str(text))
            except Exception:
                pass

    def _start_job(self, kind: str, fn):
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise RuntimeError("当前已有任务正在执行，请稍候")
            job = {"id": uuid.uuid4().hex[:8], "kind": kind, "status": "running", "result": None,
                   "error": None, "started": time.time(), "seconds": 0}
            self._job = job
        try:
            job["result"] = fn()
            job["status"] = "done"
        except Exception as e:
            job["error"] = str(e)
            job["status"] = "error"
            self.log(f"✗ 任务出错：{e}")
        finally:
            job["seconds"] = round(time.time() - job["started"], 2)
        return job["id"]

    def get_state(self):
        st = super().get_state()
        st["platform"] = "web"
        st["web"] = True
        env = st["env"]
        env["all_ready"] = all(v for k, v in env["engines"].items() if k != "pdf")
        env["pdf_font_path"] = "网页版不支持 PDF"
        st["settings"] = dict(st["settings"], report_dir="浏览器内存")
        return st

    def reset_settings(self):
        super().reset_settings()
        self.settings["report_dir"] = REPORTS
        return self.get_state()

    # 桌面专有能力在网页版里都没有
    def pick_files(self):
        return []

    def pick_folder(self):
        return ""

    def pick_mapping_file(self):
        return ""

    def reveal(self, path: str):
        return False

    def open_path(self, path: str):
        return False

    def _watch_loop(self):
        return None


API = None


def make_api(emit=None):
    global API
    for d in (UPLOADS, DOWNLOADS, REPORTS):
        os.makedirs(d, exist_ok=True)
    API = WebApi(emit=emit)
    return API


def call(name: str, args_json: str) -> str:
    """前端 /api/<name> 的统一入口，返回 {"ok": bool, "result"|"error"} 的 JSON 字符串。"""
    try:
        if name.startswith("_") or not hasattr(API, name) or not callable(getattr(API, name)):
            raise ValueError("未知接口 " + name)
        args = json.loads(args_json or "[]")
        res = getattr(API, name)(*args)
        return json.dumps({"ok": True, "result": res}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


def _safe_rel(name: str) -> str:
    parts = [p for p in str(name).replace("\\", "/").split("/") if p not in ("", ".", "..")]
    parts = ["".join("_" if c in '\\:*?"<>|' else c for c in p) for p in parts]
    return "/".join(parts) or "document"


def new_upload_dir(names_json: str) -> str:
    """为一次上传建目录并返回每个文件应写入的路径（旧的上传只保留最近几次）。"""
    olds = sorted((os.path.join(UPLOADS, d) for d in os.listdir(UPLOADS)), key=os.path.getmtime)
    for d in olds[: max(0, len(olds) - KEEP_UPLOAD_SESSIONS + 1)]:
        shutil.rmtree(d, ignore_errors=True)
    sess = os.path.join(UPLOADS, time.strftime("%H%M%S-") + uuid.uuid4().hex[:6])
    paths = []
    for n in json.loads(names_json):
        p = os.path.join(sess, _safe_rel(n))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        paths.append(p)
    return json.dumps(paths, ensure_ascii=False)


def prepare_download(kind: str, tok: str) -> str:
    """把一次下载（单个文件或打包 zip）准备成虚拟文件，返回 {path, name, mime}。"""
    entry = API._downloads.get(tok)
    if not entry or not entry["files"]:
        raise ValueError("下载已失效，请重新处理")
    files = entry["files"]
    if kind == "report":
        return json.dumps({"path": files[0], "name": "脱敏报告.html", "mime": "text/html;charset=utf-8"}, ensure_ascii=False)
    if kind == "mapping" or len(files) == 1:
        p = files[0]
        mime = "application/json" if p.endswith(".json") else "application/octet-stream"
        return json.dumps({"path": p, "name": os.path.basename(p), "mime": mime}, ensure_ascii=False)
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    zp = os.path.join(DOWNLOADS, entry["label"] + ".zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            zf.write(fp, os.path.basename(fp))
    return json.dumps({"path": zp, "name": os.path.basename(zp), "mime": "application/zip"}, ensure_ascii=False)


def file_info(path: str) -> str:
    p = os.path.abspath(path)
    if not p.startswith(ROOT + "/") or not os.path.isfile(p):
        raise ValueError("文件不存在")
    return json.dumps({"path": p, "name": os.path.basename(p), "mime": "application/json"}, ensure_ascii=False)
