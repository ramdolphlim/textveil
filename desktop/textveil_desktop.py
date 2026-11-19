#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文隐 TextVeil · 桌面端与本地网页服务端（macOS / Windows / Linux）

支持原生 pywebview 窗口与 --browser 本地 HTTP 浏览器双模式：
  * 五类文档格式全覆盖：Word (.docx) / Excel (.xlsx/.xlsm) / PPT (.pptx) / PDF (.pdf) / Markdown (.md/.txt)
  * 双脱敏模式实时切换：可逆占位符（附带一键还原） / 格式感知掩码遮蔽
  * 跨批次映射复用与监视文件夹自动脱敏
"""

import base64
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HERE)
for _p in (getattr(sys, "_MEIPASS", ""), ROOT_DIR, HERE):
    if _p and os.path.isdir(os.path.join(_p, "textveil")) and _p not in sys.path:
        sys.path.insert(0, _p)

from textveil import APP_NAME, APP_VERSION, SUPPORTED_EXTS  # noqa: E402
from textveil.config import CAT_GROUPS, CAT_NAMES, DEFAULT_CONFIG, OPTION_INFO, PRESETS, merge_config, preset_options  # noqa: E402
from textveil.formats import check_environment  # noqa: E402
from textveil.masking import load_mapping_file, mapping_export  # noqa: E402
from textveil.pipeline import apply_pipeline, collect_files, restore_pipeline, scan_pipeline  # noqa: E402

PLATFORM = "mac" if sys.platform == "darwin" else ("win" if os.name == "nt" else "linux")


def resource(*parts) -> str:
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, *parts)


def data_dir() -> str:
    if PLATFORM == "mac":
        base, name, legacy = os.path.expanduser("~/Library/Application Support"), "TextVeil", "DocVeil"
    elif PLATFORM == "win":
        base, name, legacy = os.environ.get("APPDATA") or os.path.expanduser("~"), "TextVeil", "DocVeil"
    else:
        base, name, legacy = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "textveil", "docveil"
    d = os.path.join(base, name)
    old = os.path.join(base, legacy)
    # 由旧名 DocVeil 升级：沿用已保存的设置
    if not os.path.exists(d) and os.path.isdir(old):
        try:
            os.rename(old, d)
        except OSError:
            pass
    os.makedirs(d, exist_ok=True)
    return d


def documents_dir() -> str:
    d = os.path.expanduser("~/Documents")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def default_settings() -> dict:
    return {
        "preset": DEFAULT_CONFIG["preset"],
        "mode": DEFAULT_CONFIG["mode"],
        "pdf_style": DEFAULT_CONFIG["pdf_style"],
        "options": dict(DEFAULT_CONFIG["options"]),
        "keywords": [],
        "whitelist": list(DEFAULT_CONFIG["whitelist"]),
        "pseudonyms": dict(DEFAULT_CONFIG["pseudonyms"]),
        "output_mode": "beside",  # "beside": 原文件旁「脱敏输出」 | "fixed": 固定目录
        "output_dir": "",
        "output_suffix": DEFAULT_CONFIG["output_suffix"],
        "report_dir": os.path.join(documents_dir(), "文隐报告（内部留存）"),
        "reuse_mapping": True,
        "reveal_after": True,
        "theme": "",
        "watch_enabled": False,
        "watch_dir": "",
        "watch_out_dir": "",
    }


def reveal(path: str) -> bool:
    try:
        if PLATFORM == "mac":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        elif PLATFORM == "win":
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        return True
    except Exception:
        return False


def open_path(path: str) -> bool:
    try:
        if PLATFORM == "mac":
            subprocess.Popen(["open", path])
        elif PLATFORM == "win":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


class Api:
    """桌面端 pywebview js_api 与浏览器端 /api/<method> 共用接口。"""

    def __init__(self, state_path: str | None = None):
        self._lock = threading.RLock()
        self._state_path = state_path or os.path.join(data_dir(), "state.json")
        self._logs: list[dict] = []
        self._seq = 0
        self._job = None
        self._last_scan = None
        self._downloads: dict[str, dict] = {}
        self._window = None
        self._stop = threading.Event()
        self._watch_seen = {}
        self._watch_pending = {}
        self._load()
        threading.Thread(target=self._watch_loop, daemon=True).start()

    # --------------------------------------------------------- 状态持久化
    def _load(self):
        st = {}
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            pass
        s = default_settings()
        s.update(st.get("settings") or {})
        opts = dict(DEFAULT_CONFIG["options"])
        opts.update(s.get("options") or {})
        s["options"] = opts
        ps = dict(DEFAULT_CONFIG["pseudonyms"])
        ps.update(s.get("pseudonyms") or {})
        s["pseudonyms"] = ps
        self.settings = s
        self.batches = st.get("batches") or []
        self.current = st.get("current")
        if not self.batches:
            self._new_batch("第 1 批")
        if not any(b["id"] == self.current for b in self.batches):
            self.current = self.batches[0]["id"]

    def _save(self):
        with self._lock:
            os.makedirs(os.path.dirname(os.path.abspath(self._state_path)), exist_ok=True)
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"settings": self.settings, "batches": self.batches, "current": self.current},
                    f,
                    ensure_ascii=False,
                    indent=1,
                )
            os.replace(tmp, self._state_path)

    def _batch(self, bid=None):
        bid = bid or self.current
        for b in self.batches:
            if b["id"] == bid:
                return b
        raise ValueError("批次不存在")

    def _new_batch(self, name: str, inherit=None):
        b = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "files": [],
            "mapping": [],
            "inherit": inherit,
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "watch": False,
        }
        self.batches.append(b)
        self.current = b["id"]
        return b

    def _cfg(self, mode_override=None, pdf_style_override=None) -> dict:
        s = self.settings
        return merge_config(
            {
                "mode": mode_override or s.get("mode", "placeholder"),
                "pdf_style": pdf_style_override or s.get("pdf_style", "replace"),
                "preset": s.get("preset", "standard"),
                "options": s.get("options") or {},
                "keywords": s.get("keywords") or [],
                "whitelist": s.get("whitelist") or [],
                "pseudonyms": s.get("pseudonyms") or {},
                "output_suffix": s.get("output_suffix") or "_脱敏",
            }
        )

    def _previous_mapping(self, b):
        if not self.settings.get("reuse_mapping"):
            return None
        entries = list(b.get("mapping") or [])
        inh = b.get("inherit")
        seen_terms = {e.get("term") for e in entries}
        visited = set()
        while inh and inh not in visited:
            visited.add(inh)
            pb = next((x for x in self.batches if x["id"] == inh), None)
            if not pb:
                break
            for e in pb.get("mapping") or []:
                if e.get("term") not in seen_terms:
                    entries.append(e)
                    seen_terms.add(e.get("term"))
            inh = pb.get("inherit")
        return {"entries": entries} if entries else None

    def log(self, text: str):
        with self._lock:
            self._seq += 1
            self._logs.append({"seq": self._seq, "t": time.strftime("%H:%M:%S"), "text": str(text)})
            if len(self._logs) > 600:
                self._logs = self._logs[-400:]

    # --------------------------------------------------------- 对外状态接口
    def get_state(self):
        env = check_environment()
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "platform": PLATFORM,
            "settings": self.settings,
            "current": self.current,
            "batches": [
                {
                    "id": b["id"],
                    "name": b["name"],
                    "created": b.get("created", ""),
                    "mappingCount": len(b.get("mapping") or []),
                    "fileCount": len(b.get("files") or []),
                    "watch": b.get("watch", False),
                }
                for b in self.batches
            ],
            "env": env,
            "options": [list(x) for x in OPTION_INFO],
            "cats": CAT_NAMES,
            "cat_groups": CAT_GROUPS,
            "presets": [list(x) for x in PRESETS],
            "defaults": default_settings(),
        }

    def save_settings(self, s):
        s = dict(s or {})
        if "options" in s:
            o = dict(self.settings["options"])
            o.update({k: bool(v) for k, v in (s["options"] or {}).items() if k in o})
            s["options"] = o
        if "pseudonyms" in s:
            p = dict(self.settings["pseudonyms"])
            p.update(s["pseudonyms"] or {})
            s["pseudonyms"] = p
        self.settings.update(s)
        self._save()
        return self.get_state()

    def reset_settings(self):
        self.settings = default_settings()
        self._save()
        return self.get_state()

    def apply_preset(self, preset_name: str):
        opts = preset_options(preset_name)
        patch = {"preset": preset_name, "options": opts}
        if preset_name == "ai":
            patch["mode"] = "placeholder"
        return self.save_settings(patch)

    # --------------------------------------------------------- 原生文件对话框
    def _dialog_types(self):
        import webview
        if hasattr(webview, "FileDialog"):
            return webview.FileDialog.OPEN, webview.FileDialog.FOLDER
        return webview.OPEN_DIALOG, webview.FOLDER_DIALOG

    def pick_files(self):
        if not self._window:
            return []
        open_mode, _ = self._dialog_types()
        ft = ("支持文档 (*.docx;*.xlsx;*.xlsm;*.pptx;*.pdf;*.md;*.markdown;*.txt)", "所有文件 (*.*)")
        res = self._window.create_file_dialog(open_mode, allow_multiple=True, file_types=ft)
        return list(res) if res else []

    def pick_folder(self):
        if not self._window:
            return ""
        _, folder_mode = self._dialog_types()
        res = self._window.create_file_dialog(folder_mode)
        if not res:
            return ""
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    def pick_mapping_file(self):
        if not self._window:
            return ""
        open_mode, _ = self._dialog_types()
        res = self._window.create_file_dialog(
            open_mode,
            allow_multiple=False,
            file_types=("映射表 JSON (*.json)", "所有文件 (*.*)"),
        )
        if not res:
            return ""
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    # --------------------------------------------------------- 异步任务执行
    def _start_job(self, kind: str, fn):
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise RuntimeError("当前已有任务正在执行，请稍候")
            job = {
                "id": uuid.uuid4().hex[:8],
                "kind": kind,
                "status": "running",
                "result": None,
                "error": None,
                "started": time.time(),
                "seconds": 0,
            }
            self._job = job

        def runner():
            try:
                res = fn()
                job["result"] = res
                job["status"] = "done"
            except Exception as e:
                job["error"] = str(e)
                job["status"] = "error"
                self.log(f"✗ 任务出错：{e}")
            finally:
                job["seconds"] = round(time.time() - job["started"], 2)

        threading.Thread(target=runner, daemon=True).start()
        return job["id"]

    # --------------------------------------------------------- 扫描与脱敏流程
    def start_session(self, paths):
        paths = [p for p in (paths or []) if p]
        if not paths:
            return self.get_state()
        collected = collect_files(paths, output_suffix=self.settings.get("output_suffix", "_脱敏"))
        if not collected:
            raise RuntimeError("未找到 Word / Excel / PPT / PDF / Markdown 文档")

        cur = self._batch()
        if cur.get("watch") or cur["files"]:
            inh = cur["id"] if self.settings.get("reuse_mapping") else None
            cur = self._new_batch(time.strftime("%m-%d %H:%M"), inherit=inh)
        cur["files"] = [{"path": a, "rel": r, "selected": True} for a, r in collected]
        self._save()
        self.scan()
        return self.get_state()

    def scan(self):
        b = self._batch()
        files = [(f["path"], f["rel"]) for f in b["files"] if f.get("selected", True)]
        if not files:
            raise RuntimeError("当前批次没有待扫描文档")
        cfg = self._cfg()
        prev = self._previous_mapping(b)

        def work():
            self.log(f"➤ 开始扫描「{b['name']}」：{len(files)} 份文档")
            res = scan_pipeline(files, cfg, previous_mapping=prev, log=self.log)
            self._last_scan = {"batch_id": b["id"], "files": files, "scan_result": res}
            self.log(f"✓ 扫描完成：识别 {len(res['terms'])} 项敏感内容，用时 {res['seconds']}s")
            return {
                "files": res["files"],
                "file_stats": res["file_stats"],
                "format_counts": res["format_counts"],
                "meta_totals": res["meta_totals"],
                "errors": res["errors"],
                "terms": res["terms"],
                "seconds": res["seconds"],
                "mode": cfg["mode"],
            }

        return self._start_job("scan", work)

    def add_keyword_and_rescan(self, raw_kw: str):
        raw_kw = (raw_kw or "").strip()
        if not raw_kw:
            return self.get_state()
        kws = list(self.settings.get("keywords") or [])
        if raw_kw not in kws:
            kws.append(raw_kw)
            self.settings["keywords"] = kws
            self._save()
        self.scan()
        return self.get_state()

    def apply(self, decisions=None, mode_override=None, pdf_style_override=None):
        b = self._batch()
        files = [(f["path"], f["rel"]) for f in b["files"] if f.get("selected", True)]
        if not files:
            raise RuntimeError("没有可执行脱敏的文档")
        if mode_override in ("placeholder", "mask"):
            self.settings["mode"] = mode_override
        if pdf_style_override in ("replace", "blackbox"):
            self.settings["pdf_style"] = pdf_style_override
        self._save()
        cfg = self._cfg(mode_override=mode_override, pdf_style_override=pdf_style_override)
        prev = self._previous_mapping(b)
        scan_cached = None
        if self._last_scan and self._last_scan.get("batch_id") == b["id"]:
            scan_cached = self._last_scan.get("scan_result")

        def work():
            return self._process_batch(b, files, cfg, decisions=decisions or {}, prev=prev, scan_result=scan_cached)

        return self._start_job("apply", work)

    def _register_download(self, paths: list[str], label: str) -> str:
        tok = uuid.uuid4().hex[:12]
        self._downloads[tok] = {"files": [p for p in paths if p and os.path.isfile(p)], "label": label}
        return tok

    def _process_batch(
        self,
        b: dict,
        files: list[tuple[str, str]],
        cfg: dict,
        decisions=None,
        prev=None,
        scan_result=None,
        label="执行脱敏",
        out_dir_override=None,
    ):
        s = self.settings
        self.log(f"➤ {label}「{b['name']}」：{len(files)} 份文档")
        tmp_out = tempfile.mkdtemp(prefix="textveil_out_")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_batch = re.sub(r'[\\/:*?"<>|]', "_", b["name"])
        rep_dir = os.path.join(s.get("report_dir") or os.path.join(documents_dir(), "文隐报告（内部留存）"), safe_batch, stamp)

        try:
            res = apply_pipeline(
                files,
                out_dir=tmp_out,
                cfg=cfg,
                report_dir=rep_dir,
                decisions=decisions,
                previous_mapping=prev,
                scan_result=scan_result,
                log=self.log,
            )

            final_outputs = []
            jobs_view = []
            for j in res["jobs"]:
                src = j["src"]
                out_tmp = j.get("output") or ""
                dest = ""
                if out_tmp and os.path.isfile(out_tmp):
                    if out_dir_override:
                        dest_dir = out_dir_override
                    elif s.get("output_mode") == "fixed" and s.get("output_dir"):
                        dest_dir = s["output_dir"]
                    else:
                        dest_dir = os.path.join(os.path.dirname(src), "脱敏输出")
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(dest_dir, os.path.basename(out_tmp))
                    shutil.move(out_tmp, dest)
                    final_outputs.append(dest)

                v = j.get("verify") or {}
                jobs_view.append(
                    {
                        "rel": j["rel"],
                        "src": src,
                        "output": dest,
                        "changes": len(j.get("changes", [])),
                        "removed": j.get("removed", []),
                        "notes": j.get("notes", []),
                        "error": j.get("error", ""),
                        "structure_ok": v.get("structure_ok", False),
                        "structure_msg": v.get("structure_msg", ""),
                        "residual": (v.get("residual") or [])[:10],
                    }
                )

            # 合并保存到当前批次的代号库，供下批复用与还原页使用
            old_map = {e["term"]: e for e in (b.get("mapping") or []) if e.get("term")}
            for e in mapping_export(res["mapping"])["entries"]:
                old_map[e["term"]] = e
            b["mapping"] = list(old_map.values())
            b["mapping_json"] = res.get("mapping_json", "")
            self._save()

            dl_token = self._register_download(final_outputs, f"{safe_batch}_脱敏文档")
            rep_token = self._register_download([res.get("report_html", "")], "脱敏报告.html")
            map_token = self._register_download([res.get("mapping_json", "")], "映射表.json")

            self.log(f"✓ 完成：{res['ok']} / {res['total']} 份校验通过 · 报告保存于 {rep_dir}")
            if s.get("reveal_after") and final_outputs and label == "执行脱敏" and self._window:
                reveal(final_outputs[0])

            return {
                "files": jobs_view,
                "report_dir": rep_dir,
                "report_html": res.get("report_html", ""),
                "mapping_json": res.get("mapping_json", ""),
                "ok": res["ok"],
                "total": res["total"],
                "seconds": res["seconds"],
                "mode": cfg["mode"],
                "download_token": dl_token,
                "report_token": rep_token,
                "mapping_token": map_token,
            }
        finally:
            shutil.rmtree(tmp_out, ignore_errors=True)

    # --------------------------------------------------------- 可逆还原接口
    def list_saved_mappings(self):
        items = []
        for b in reversed(self.batches):
            entries = b.get("mapping") or []
            if not entries:
                continue
            items.append(
                {
                    "id": b["id"],
                    "name": b["name"],
                    "created": b.get("created", ""),
                    "count": len(entries),
                    "mapping_json": b.get("mapping_json", ""),
                }
            )
        return items

    def restore_preview(self, paths, mapping_source):
        files = collect_files(paths or [], skip_redacted=False)
        if not files:
            raise RuntimeError("未找到待还原文档")
        if isinstance(mapping_source, str) and mapping_source.startswith("batch:"):
            bid = mapping_source.split(":", 1)[1]
            b = self._batch(bid)
            mdata = {"mode": "placeholder", "entries": b.get("mapping") or []}
        elif isinstance(mapping_source, str):
            mdata = load_mapping_file(mapping_source)
        else:
            mdata = mapping_source

        from textveil.masking import build_inverse_mapping
        inv_map, warnings = build_inverse_mapping(mdata)
        return {
            "files": [{"path": a, "rel": r} for a, r in files],
            "inv_count": len(inv_map),
            "warnings": warnings,
            "sample_pairs": [{"code": k, "orig": v} for k, v in list(inv_map.items())[:8]],
        }

    def restore_apply(self, paths, mapping_source):
        files = collect_files(paths or [], skip_redacted=False)
        if not files:
            raise RuntimeError("未找到待还原文档")
        if isinstance(mapping_source, str) and mapping_source.startswith("batch:"):
            bid = mapping_source.split(":", 1)[1]
            b = self._batch(bid)
            mdata = {"mode": "placeholder", "entries": b.get("mapping") or []}
        elif isinstance(mapping_source, str):
            mdata = mapping_source
        else:
            mdata = mapping_source

        cfg = self._cfg()
        s = self.settings

        def work():
            tmp_out = tempfile.mkdtemp(prefix="textveil_restore_")
            try:
                res = restore_pipeline(files, mdata, out_dir=tmp_out, cfg=cfg, log=self.log)
                final_outputs = []
                jobs_view = []
                for j in res["jobs"]:
                    src = j["src"]
                    out_tmp = j.get("output") or ""
                    dest = ""
                    if out_tmp and os.path.isfile(out_tmp):
                        if s.get("output_mode") == "fixed" and s.get("output_dir"):
                            dest_dir = s["output_dir"]
                        else:
                            dest_dir = os.path.join(os.path.dirname(src), "还原输出")
                        os.makedirs(dest_dir, exist_ok=True)
                        dest = os.path.join(dest_dir, os.path.basename(out_tmp))
                        shutil.move(out_tmp, dest)
                        final_outputs.append(dest)
                    v = j.get("verify") or {}
                    jobs_view.append(
                        {
                            "rel": j["rel"],
                            "output": dest,
                            "restored_count": j.get("restored_count", 0),
                            "error": j.get("error", ""),
                            "structure_ok": v.get("structure_ok", False),
                            "structure_msg": v.get("structure_msg", ""),
                            "unmapped": j.get("unmapped_placeholders", []),
                        }
                    )

                dl_token = self._register_download(final_outputs, "还原文档")
                if s.get("reveal_after") and final_outputs and self._window:
                    reveal(final_outputs[0])
                self.log(f"✓ 还原完成：{res['ok']} / {res['total']} 份成功")
                return {
                    "files": jobs_view,
                    "warnings": res["warnings"],
                    "inv_count": res["inv_count"],
                    "ok": res["ok"],
                    "total": res["total"],
                    "seconds": res["seconds"],
                    "download_token": dl_token,
                }
            finally:
                shutil.rmtree(tmp_out, ignore_errors=True)

        return self._start_job("restore", work)

    # --------------------------------------------------------- 轮询与辅助
    def poll(self, since=0):
        with self._lock:
            logs = [l for l in self._logs if l["seq"] > (since or 0)]
            job = None
            if self._job:
                job = {k: self._job.get(k) for k in ("id", "kind", "status", "error", "seconds")}
                if self._job["status"] != "running":
                    job["result"] = self._job.get("result")
            return {
                "logs": logs,
                "seq": self._seq,
                "job": job,
                "current": self.current,
            }

    def export_mapping(self, bid=None):
        b = self._batch(bid)
        d = self.settings.get("report_dir") or documents_dir()
        os.makedirs(d, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]', "_", b["name"])
        p = os.path.join(d, f"{safe}_映射表.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(
                {"tool": "TextVeil", "version": APP_VERSION, "mode": "placeholder", "entries": b.get("mapping") or []},
                f,
                ensure_ascii=False,
                indent=2,
            )
        reveal(p)
        return p

    def reveal(self, path: str):
        return reveal(path)

    def open_path(self, path: str):
        return open_path(path)

    # --------------------------------------------------------- 监视文件夹守护线程
    def _watch_batch(self):
        b = next((x for x in self.batches if x.get("watch")), None)
        if b is None:
            b = {
                "id": uuid.uuid4().hex[:12],
                "name": "监视文件夹",
                "files": [],
                "mapping": [],
                "inherit": None,
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "watch": True,
            }
            self.batches.append(b)
            self._save()
        return b

    def _watch_loop(self):
        while not self._stop.wait(4.0):
            try:
                s = self.settings
                d = s.get("watch_dir")
                if not s.get("watch_enabled") or not d or not os.path.isdir(d):
                    continue
                if self._job and self._job["status"] == "running":
                    continue
                suffix = s.get("output_suffix") or "_脱敏"
                ready = []
                for name in sorted(os.listdir(d)):
                    p = os.path.join(d, name)
                    if not os.path.isfile(p):
                        continue
                    st, ext = os.path.splitext(name)
                    if ext.lower() not in SUPPORTED_EXTS or st.endswith(suffix) or name.startswith((".", "~$")):
                        continue
                    try:
                        sig = (os.path.getsize(p), os.path.getmtime(p))
                    except OSError:
                        continue
                    if self._watch_seen.get(p) == sig:
                        continue
                    if self._watch_pending.get(p) == sig:
                        ready.append(p)
                    self._watch_pending[p] = sig
                if not ready:
                    continue

                b = self._watch_batch()
                files = [(p, os.path.basename(p)) for p in ready]
                out = s.get("watch_out_dir") or os.path.join(d, "已脱敏")
                cfg = self._cfg()
                with self._lock:
                    self._job = {
                        "id": uuid.uuid4().hex[:8],
                        "kind": "watch",
                        "status": "running",
                        "result": None,
                        "error": None,
                        "started": time.time(),
                        "seconds": 0,
                    }
                    job = self._job
                try:
                    job["result"] = self._process_batch(
                        b, files, cfg, decisions={}, prev=self._previous_mapping(b), label="自动脱敏", out_dir_override=out
                    )
                    job["status"] = "done"
                except Exception as e:
                    job["status"] = "error"
                    job["error"] = str(e)
                finally:
                    job["seconds"] = round(time.time() - job["started"], 2)
                for p in ready:
                    try:
                        self._watch_seen[p] = (os.path.getsize(p), os.path.getmtime(p))
                    except OSError:
                        pass
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 启动模式：原生 pywebview 与 --browser 本地 HTTP 服务
# ---------------------------------------------------------------------------

def run_native(api: Api):
    import webview

    w = webview.create_window(
        APP_NAME,
        url=resource("ui", "index.html"),
        js_api=api,
        width=1140,
        height=780,
        min_size=(860, 620),
        text_select=True,
    )
    api._window = w

    def on_drop(e):
        try:
            files = e.get("dataTransfer", {}).get("files", [])
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                api.start_session(paths)
        except Exception:
            pass

    def bind():
        try:
            from webview.dom import DOMEventHandler
            w.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    w.events.loaded += bind
    webview.start(http_server=True, debug=("--debug" in sys.argv))


def run_browser(api: Api, port: int = 0, open_browser: bool = True, server_out=None):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    ui = resource("ui")
    upload_root = os.path.join(data_dir(), "browser_uploads")
    os.makedirs(upload_root, exist_ok=True)
    types = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".css": "text/css; charset=utf-8",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body, ctype: str, headers: dict | None = None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?", 1)[0]

            # 下载打包输出文档
            if p.startswith("/download/"):
                tok = p.split("/download/", 1)[1]
                entry = api._downloads.get(tok)
                if not entry or not entry["files"]:
                    return self._send(404, "download expired", "text/plain; charset=utf-8")
                files = entry["files"]
                if len(files) == 1:
                    fp = files[0]
                    fn = urllib.parse.quote(os.path.basename(fp))
                    ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                    with open(fp, "rb") as f:
                        return self._send(
                            200,
                            f.read(),
                            ctype,
                            {"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"},
                        )
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp in files:
                        zf.write(fp, os.path.basename(fp))
                fn = urllib.parse.quote(f"{entry['label']}.zip")
                return self._send(
                    200,
                    buf.getvalue(),
                    "application/zip",
                    {"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"},
                )

            if p.startswith("/report/"):
                tok = p.split("/report/", 1)[1]
                entry = api._downloads.get(tok)
                if not entry or not entry["files"]:
                    return self._send(404, "report not found", "text/plain; charset=utf-8")
                with open(entry["files"][0], "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")

            if p.startswith("/mapping/"):
                tok = p.split("/mapping/", 1)[1]
                entry = api._downloads.get(tok)
                if not entry or not entry["files"]:
                    return self._send(404, "mapping not found", "text/plain; charset=utf-8")
                fn = urllib.parse.quote(os.path.basename(entry["files"][0]))
                with open(entry["files"][0], "rb") as f:
                    return self._send(
                        200,
                        f.read(),
                        "application/json; charset=utf-8",
                        {"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"},
                    )

            p = "/index.html" if p == "/" else p
            full = os.path.normpath(os.path.join(ui, p.lstrip("/")))
            if not full.startswith(os.path.normpath(ui)) or not os.path.isfile(full):
                return self._send(404, "not found", "text/plain")
            with open(full, "rb") as f:
                self._send(200, f.read(), types.get(os.path.splitext(full)[1], "application/octet-stream"))

        def do_POST(self):
            if self.path == "/api/upload":
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                    sess_dir = os.path.join(upload_root, uuid.uuid4().hex[:10])
                    os.makedirs(sess_dir, exist_ok=True)
                    saved = []
                    for item in payload.get("files") or []:
                        raw_name = os.path.basename(item.get("name") or "document")
                        safe_name = re.sub(r'[\\/:*?"<>|]', "_", raw_name)
                        dst = os.path.join(sess_dir, safe_name)
                        with open(dst, "wb") as f:
                            f.write(base64.b64decode(item.get("data_b64") or ""))
                        saved.append(dst)
                    return self._send(
                        200,
                        json.dumps({"ok": True, "result": {"paths": saved, "session_dir": sess_dir}}, ensure_ascii=False),
                        "application/json; charset=utf-8",
                    )
                except Exception as e:
                    return self._send(
                        200,
                        json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                        "application/json; charset=utf-8",
                    )

            m = re.match(r"^/api/([a-z0-9_]+)$", self.path)
            if not m or m.group(1).startswith("_") or not hasattr(api, m.group(1)):
                return self._send(404, json.dumps({"error": "unknown"}), "application/json")
            try:
                n = int(self.headers.get("Content-Length", "0"))
                args = json.loads(self.rfile.read(n).decode("utf-8") or "[]")
                res = getattr(api, m.group(1))(*args)
                self._send(200, json.dumps({"ok": True, "result": res}, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if server_out is not None:
        server_out["server"] = srv
        server_out["port"] = srv.server_address[1]
    url = f"http://127.0.0.1:{srv.server_address[1]}/?mode=browser"
    print(f"{APP_NAME} 已启动：{url}", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    api = Api()
    if "--browser" in sys.argv:
        port = 0
        for a in sys.argv:
            if a.startswith("--port="):
                port = int(a.split("=", 1)[1])
        return run_browser(api, port=port, open_browser="--no-open" not in sys.argv)
    try:
        import webview  # noqa: F401
    except ImportError:
        print("未安装 pywebview，改用本地浏览器视图")
        return run_browser(api)
    run_native(api)


if __name__ == "__main__":
    main()
