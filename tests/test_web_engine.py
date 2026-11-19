#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页版引擎回归测试：用 web/dist 里的 engine.zip + libs.zip（和浏览器里加载的完全一样）跑一遍完整流程。

先运行 python web/build_web.py，再运行本文件。PDF 不在网页版范围内，这里只测另外 4 种格式。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT_DIR, "web", "dist")

CHILD = r'''
import glob, json, os, shutil, sys, zipfile
tmp, samples = sys.argv[1], sys.argv[2]
sys.path[:0] = [os.path.join(tmp, "app"), os.path.join(tmp, "lib")]
import docx
assert docx.__file__.startswith(tmp), "python-docx 应来自 libs.zip: " + docx.__file__
import web_api as W
logs = []
W.make_api(logs.append)

def call(n, *a):
    r = json.loads(W.call(n, json.dumps(list(a))))
    assert r["ok"], (n, r.get("error"))
    return r["result"]

st = call("get_state")
# 浏览器里没有 PyMuPDF；CI 上可能装了，所以这里不检查 pdf 引擎
assert st["web"] and st["env"]["all_ready"], st["env"]
src = sorted(p for p in glob.glob(os.path.join(samples, "*")) if not p.endswith(".pdf"))
assert len(src) == 4, src
paths = json.loads(W.new_upload_dir(json.dumps(["文件夹/" + os.path.basename(p) for p in src])))
for s, d in zip(src, paths):
    shutil.copy(s, d)
call("start_session", paths)
job = call("poll", 0)["job"]
assert job["kind"] == "scan" and job["status"] == "done", job
assert len(job["result"]["terms"]) >= 20, len(job["result"]["terms"])
assert logs, "日志应实时推送给页面"

call("apply", {}, "placeholder", "replace")
job = call("poll", 0)["job"]
r = job["result"]
assert job["status"] == "done" and r["ok"] == r["total"] == 4, job
zp = json.loads(W.prepare_download("download", r["download_token"]))["path"]
assert len(zipfile.ZipFile(zp).namelist()) == 4
assert json.loads(W.prepare_download("report", r["report_token"]))["name"] == "脱敏报告.html"
mj = json.loads(W.prepare_download("mapping", r["mapping_token"]))["path"]

red = [f["output"] for f in r["files"] if f["output"].endswith(".docx")][0]
assert "北京云枢" not in "\n".join(p.text for p in docx.Document(red).paragraphs)

outs = [f["output"] for f in r["files"] if f["output"]]
up = json.loads(W.new_upload_dir(json.dumps(["映射表.json"])))[0]
shutil.copy(mj, up)
assert call("restore_preview", outs, up)["inv_count"] > 0
call("restore_apply", outs, up)
job = call("poll", 0)["job"]
assert job["status"] == "done" and job["result"]["ok"] == 4, job
back = [f["output"] for f in job["result"]["files"] if f["output"].endswith(".docx")][0]
assert "北京云枢" in "\n".join(p.text for p in docx.Document(back).paragraphs)

p = call("export_mapping")
assert json.loads(W.file_info(p))["name"].endswith("映射表.json")
call("save_settings", {"mode": "mask"})
saved = json.load(open(os.path.join(tmp, "persist", "settings.json"), encoding="utf-8"))
assert saved["settings"]["mode"] == "mask" and "batches" not in saved, "只应保存设置，不保存含原文的映射表"
assert call("get_state")["settings"]["report_dir"] == "浏览器内存"
assert W.API.settings["report_dir"] == W.REPORTS
print("网页版引擎测试通过：扫描 / 脱敏 / 下载 / 还原 / 设置保存")
'''


def main():
    for n in ("engine.zip", "libs.zip"):
        if not os.path.isfile(os.path.join(DIST, n)):
            raise SystemExit("请先运行 python web/build_web.py")
    tmp = tempfile.mkdtemp(prefix="tv_web_")
    try:
        zipfile.ZipFile(os.path.join(DIST, "engine.zip")).extractall(os.path.join(tmp, "app"))
        zipfile.ZipFile(os.path.join(DIST, "libs.zip")).extractall(os.path.join(tmp, "lib"))
        samples = os.path.join(tmp, "samples")
        subprocess.check_call([sys.executable, os.path.join(ROOT_DIR, "tests", "make_samples.py"), samples], stdout=subprocess.DEVNULL)
        env = dict(os.environ, TEXTVEIL_WEB_ROOT=os.path.join(tmp, "tv"), TEXTVEIL_WEB_PERSIST=os.path.join(tmp, "persist"))
        # -I：隔离运行，确保用的是 zip 里的代码而不是仓库里的
        subprocess.check_call([sys.executable, "-I", "-c", CHILD, tmp, samples], env=env, cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
