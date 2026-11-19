#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文隐 TextVeil 全流程自动化回归测试。"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import docx
import openpyxl
import pptx
import pymupdf

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from textveil.config import merge_config, preset_options
from textveil.detectors import Detector, idcard_ok, ipv4_ok, luhn_ok, name_like, uscc_ok
from textveil.formats import ooxml_utils as ox
from textveil.masking import build_inverse_mapping, mask_value
from textveil.pipeline import apply_pipeline, collect_files, restore_pipeline, scan_pipeline
from tests.make_samples import SAMPLE_BANK1, SAMPLE_ID1, SAMPLE_USCC1, make_all


def test_detectors():
    print("[1/5] 测试规则引擎与校验位算法...")
    assert idcard_ok(SAMPLE_ID1)
    assert not idcard_ok("110101199003071230")
    assert uscc_ok(SAMPLE_USCC1)
    assert not uscc_ok("91110108MA01ABCD2A")
    assert luhn_ok(SAMPLE_BANK1)
    assert not luhn_ok("6222021001122330")
    assert ipv4_ok("192.168.1.10")
    assert not ipv4_ok("1.2.3.4", "v", "")
    assert name_like("张伟") and name_like("欧阳明") and name_like("John Doe")
    assert not name_like("合计") and not name_like("公司")

    cfg = merge_config({"keywords": ["内部代号=ProjectX", r"re:SECRET-\d{4}"]})
    det = Detector(cfg)
    hits = det.detect_text("测试内部代号以及编号 SECRET-9527 和白名单中华人民共和国")
    terms = {t for t, _, _, _ in hits}
    assert "内部代号" in terms
    assert "SECRET-9527" in terms
    assert "中华人民共和国" not in terms

    # 掩码格式验证
    assert mask_value("13812345678", "phone") == "138****5678"
    assert mask_value("zhangwei@yunshu-cloud.cn", "email") == "z***@***.cn"
    assert mask_value("张伟", "person") == "张*"
    assert mask_value("欧阳明", "person") == "欧**"
    assert mask_value("北京云枢科技有限公司", "company") == "某****科技有限公司"
    assert mask_value(SAMPLE_ID1, "idcard").startswith("110101********")

    # 不可逆掩码碰撞检测
    _, warns = build_inverse_mapping(
        [
            {"term": "秘词A", "replace": "****", "enabled": True},
            {"term": "秘词B", "replace": "****", "enabled": True},
        ]
    )
    assert any("无法唯一还原" in w for w in warns)


def test_placeholder_and_restore_roundtrip(tmp_dir: str, samples: dict):
    print("[2/5] 测试 5 类格式可逆占位符脱敏与一键还原...")
    files = collect_files([os.path.dirname(samples["docx"])])
    assert len(files) == 5

    cfg = merge_config({"mode": "placeholder", "preset": "ai", "options": preset_options("ai")})
    out_dir = os.path.join(tmp_dir, "out_placeholder")
    res = apply_pipeline(files, out_dir, cfg)
    assert res["ok"] == 5 and res["total"] == 5, f"脱敏校验失败: {res['jobs']}"
    assert os.path.isfile(res["report_html"])
    assert os.path.isfile(res["mapping_json"])
    assert os.path.isfile(res["mapping_csv"])
    assert os.path.isfile(res["detail_csv"])

    # 验证输出目录的 5 份脱敏文档残留为 0 且结构完好
    out_map = {os.path.basename(j["src"]): j["output"] for j in res["jobs"]}

    # DOCX 验证
    docx_out = out_map["样例_商业合作协议.docx"]
    d = docx.Document(docx_out)
    assert len(d.paragraphs) > 0
    _, entries = ox.read_zip_entries(docx_out)
    assert "word/comments.xml" not in entries
    all_docx_txt = ox.collect_all_xml_text(entries)
    for secret in ("张伟", "13812345678", "北京云枢科技有限公司", "sk-proj-DeletedTrackSecret99887766", "赵强", "13900001111"):
        assert secret not in all_docx_txt, f"DOCX 残留 {secret}"
    assert "中华人民共和国" in all_docx_txt

    # XLSX 验证（公式不变，字符串字面量与隐藏表内容已脱敏）
    xlsx_out = out_map["样例_员工与项目台账.xlsx"]
    wb = openpyxl.load_workbook(xlsx_out, data_only=False)
    assert wb["项目台账"]["F4"].value == "=SUM(F2:F3)"
    assert "负责" in wb["项目台账"]["G4"].value and "张伟" not in wb["项目台账"]["G4"].value
    assert "sk-proj-XlsxHiddenKeyAbCdEf12345678" not in str(wb["内部密钥"]["B2"].value)
    wb.close()

    # PPTX 验证
    pptx_out = out_map["样例_项目汇报方案.pptx"]
    prs = pptx.Presentation(pptx_out)
    assert len(prs.slides) == 2
    _, p_entries = ox.read_zip_entries(pptx_out)
    assert "ppt/comments/comment1.xml" not in p_entries
    assert "ghp_1234567890abcdef1234567890abcdef1234" not in ox.collect_all_xml_text(p_entries)

    # PDF 验证（文字物理删除、元数据清空、批注移除、页数不变）
    pdf_out = out_map["样例_技术架构与合同摘要.pdf"]
    pdf_doc = pymupdf.open(pdf_out)
    assert len(pdf_doc) == 2
    pdf_txt = pdf_doc[0].get_text("text")
    for secret in ("陈敏", "13666667777", "北京云枢科技有限公司", "sk-proj-PdfSecretToken9876543210abcd", "mysql://root:DbPass123@10.0.1.50:3306/app"):
        assert secret not in pdf_txt, f"PDF 残留 {secret}"
    assert "中华人民共和国" in pdf_txt
    assert not (pdf_doc.metadata or {}).get("author")
    assert len(list(pdf_doc[0].annots() or [])) == 0
    pdf_doc.close()

    # MD 验证
    md_out = out_map["样例_系统运维手册.md"]
    with open(md_out, "r", encoding="utf-8") as f:
        md_txt = f.read()
    assert "sk-proj-MdCodeBlockSecret1234567890" not in md_txt
    assert "10.88.12.34" not in md_txt
    assert "v1.2.3.4" in md_txt and "127.0.0.1" in md_txt and "中华人民共和国" in md_txt

    # 一键逆向还原全 5 格式验证
    out_files = collect_files([out_dir], skip_redacted=False)
    assert len(out_files) == 5
    restore_dir = os.path.join(tmp_dir, "restored")
    rres = restore_pipeline(out_files, res["mapping_json"], restore_dir, cfg)
    assert rres["ok"] == 5 and rres["total"] == 5
    r_map = {os.path.basename(j["src"]): j["output"] for j in rres["jobs"]}

    # 检查每个格式还原后的正文是否完整恢复原文
    _, r_docx_entries = ox.read_zip_entries(r_map["样例_商业合作协议_脱敏.docx"])
    r_docx_txt = ox.collect_all_xml_text(r_docx_entries)
    assert "北京云枢科技有限公司" in r_docx_txt and "13812345678" in r_docx_txt and "赵强" in r_docx_txt

    r_wb = openpyxl.load_workbook(r_map["样例_员工与项目台账_脱敏.xlsx"], data_only=False)
    assert r_wb["项目台账"]["A2"].value == "张伟"
    assert "张伟负责" in r_wb["项目台账"]["G4"].value
    assert r_wb["内部密钥"]["B2"].value == "sk-proj-XlsxHiddenKeyAbCdEf12345678"
    r_wb.close()

    _, r_pptx_entries = ox.read_zip_entries(r_map["样例_项目汇报方案_脱敏.pptx"])
    r_pptx_txt = ox.collect_all_xml_text(r_pptx_entries)
    assert "杭州星澜智能研究院" in r_pptx_txt and "ghp_1234567890abcdef1234567890abcdef1234" in r_pptx_txt

    r_pdf = pymupdf.open(r_map["样例_技术架构与合同摘要_脱敏.pdf"])
    r_pdf_txt = r_pdf[0].get_text("text")
    assert "北京云枢科技有限公司" in r_pdf_txt and "13666667777" in r_pdf_txt
    assert "sk-proj-PdfSecretToken9876543210abcd" in r_pdf_txt
    r_pdf.close()

    with open(r_map["样例_系统运维手册_脱敏.md"], "r", encoding="utf-8") as f:
        r_md_txt = f.read()
    assert "sk-proj-MdCodeBlockSecret1234567890" in r_md_txt
    assert "10.88.12.34" in r_md_txt


def test_mask_and_strict_modes(tmp_dir: str, samples: dict):
    print("[3/5] 测试掩码遮蔽、PDF 黑块涂黑与严格删除隐藏表模式...")
    files = collect_files([os.path.dirname(samples["docx"])])
    cfg = merge_config(
        {
            "mode": "mask",
            "pdf_style": "blackbox",
            "preset": "strict",
            "options": preset_options("strict"),
        }
    )
    out_dir = os.path.join(tmp_dir, "out_mask")
    res = apply_pipeline(files, out_dir, cfg)
    assert res["ok"] == 5 and res["total"] == 5

    out_map = {os.path.basename(j["src"]): j["output"] for j in res["jobs"]}

    # 严格模式下 Excel 隐藏表应被删除
    wb = openpyxl.load_workbook(out_map["样例_员工与项目台账.xlsx"])
    assert "内部密钥" not in wb.sheetnames
    assert wb["项目台账"]["B2"].value == "138****5678"
    wb.close()

    # MD 掩码形式检查
    with open(out_map["样例_系统运维手册.md"], "r", encoding="utf-8") as f:
        md = f.read()
    assert "137****2222" in md
    assert "某****科技有限公司" in md
    assert "sk-proj-************" in md

    # PDF 黑块涂黑后不应残留原文
    pdf_doc = pymupdf.open(out_map["样例_技术架构与合同摘要.pdf"])
    txt = pdf_doc[0].get_text("text")
    assert "陈敏" not in txt and "13666667777" not in txt and "sk-proj-PdfSecretToken9876543210abcd" not in txt
    pdf_doc.close()


def test_cli(tmp_dir: str, samples: dict):
    print("[4/5] 测试命令行工具 (check / scan / run --dry-run / run / restore)...")
    py = sys.executable
    cli = os.path.join(ROOT_DIR, "doc_desensitize.py")
    sample_dir = os.path.dirname(samples["docx"])

    r1 = subprocess.run([py, cli, "check"], capture_output=True, text=True, check=True)
    assert "Word (.docx)" in r1.stdout

    r2 = subprocess.run([py, cli, "scan", sample_dir, "--json"], capture_output=True, text=True, check=True)
    j2 = json.loads(r2.stdout)
    assert j2["files"] == 5 and len(j2["terms"]) >= 30

    cli_out = os.path.join(tmp_dir, "cli_out")
    subprocess.run([py, cli, "run", sample_dir, "-o", cli_out, "--dry-run"], check=True, capture_output=True)
    assert not os.path.exists(os.path.join(cli_out, "样例_系统运维手册_脱敏.md"))

    subprocess.run([py, cli, "run", sample_dir, "-o", cli_out, "--mode", "placeholder"], check=True, capture_output=True)
    map_p = os.path.join(cli_out, "_脱敏报告(含原文,勿外发)", "映射表.json")
    assert os.path.isfile(map_p)

    cli_res = os.path.join(tmp_dir, "cli_restored")
    subprocess.run([py, cli, "restore", cli_out, "-m", map_p, "-o", cli_res], check=True, capture_output=True)
    assert os.path.isfile(os.path.join(cli_res, "样例_系统运维手册_已还原.md"))


def test_desktop_http_server(tmp_dir: str, samples: dict):
    print("[5/5] 测试桌面端 HTTP 服务与上传/扫描/脱敏/下载/还原接口...")
    from desktop.textveil_desktop import Api, run_browser

    state_file = os.path.join(tmp_dir, "test_state.json")
    api = Api(state_path=state_file)
    api.settings["reveal_after"] = False
    api.settings["report_dir"] = os.path.join(tmp_dir, "reports")
    srv_info = {}
    th = threading.Thread(
        target=run_browser,
        args=(api, 0, False, srv_info),
        daemon=True,
    )
    th.start()
    for _ in range(50):
        if "port" in srv_info:
            break
        time.sleep(0.05)
    port = srv_info["port"]
    base = f"http://127.0.0.1:{port}"

    try:
        # 静态资源检查
        for p in ("/", "/app.css", "/app.js", "/favicon.svg"):
            with urllib.request.urlopen(base + p) as resp:
                assert resp.status == 200 and len(resp.read()) > 50

        def post(ep: str, body):
            req = urllib.request.Request(
                base + ep,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data["ok"], f"{ep} error: {data}"
                return data["result"]

        st = post("/api/get_state", [])
        assert st["env"]["all_ready"] is True

        # 上传 MD 与 DOCX 文件
        upload_payload = {"files": []}
        for k in ("md", "docx"):
            with open(samples[k], "rb") as f:
                upload_payload["files"].append(
                    {"name": os.path.basename(samples[k]), "data_b64": base64.b64encode(f.read()).decode("ascii")}
                )
        up = post("/api/upload", upload_payload)
        assert len(up["paths"]) == 2

        post("/api/start_session", [up["paths"]])
        scan_job = None
        for _ in range(80):
            p = post("/api/poll", [0])
            if p["job"] and p["job"]["kind"] == "scan" and p["job"]["status"] != "running":
                scan_job = p["job"]
                break
            time.sleep(0.1)
        assert scan_job and scan_job["status"] == "done"

        post("/api/apply", [{}, "placeholder", "replace"])
        apply_job = None
        for _ in range(80):
            p = post("/api/poll", [0])
            if p["job"] and p["job"]["kind"] == "apply" and p["job"]["status"] != "running":
                apply_job = p["job"]
                break
            time.sleep(0.1)
        assert apply_job and apply_job["status"] == "done"
        ares = apply_job["result"]
        assert ares["ok"] == 2 and ares["total"] == 2

        # 验证下载链接、HTML 报告链接与映射表链接
        with urllib.request.urlopen(base + "/download/" + ares["download_token"]) as resp:
            assert resp.status == 200 and len(resp.read()) > 200
        with urllib.request.urlopen(base + "/report/" + ares["report_token"]) as resp:
            assert resp.status == 200 and "脱敏校验报告" in resp.read().decode("utf-8")
        with urllib.request.urlopen(base + "/mapping/" + ares["mapping_token"]) as resp:
            mjson = json.loads(resp.read().decode("utf-8"))
            assert len(mjson["entries"]) > 0

        # 验证还原接口
        out_paths = [f["output"] for f in ares["files"]]
        pv = post("/api/restore_preview", [out_paths, ares["mapping_json"]])
        assert pv["inv_count"] > 0

        post("/api/restore_apply", [out_paths, ares["mapping_json"]])
        rs_job = None
        for _ in range(80):
            p = post("/api/poll", [0])
            if p["job"] and p["job"]["kind"] == "restore" and p["job"]["status"] != "running":
                rs_job = p["job"]
                break
            time.sleep(0.1)
        assert rs_job and rs_job["status"] == "done"
        assert rs_job["result"]["ok"] == 2
    finally:
        if "server" in srv_info:
            srv_info["server"].shutdown()
            srv_info["server"].server_close()


def main():
    tmp_dir = tempfile.mkdtemp(prefix="textveil_test_")
    try:
        sample_dir = os.path.join(tmp_dir, "samples")
        samples = make_all(sample_dir)
        test_detectors()
        test_placeholder_and_restore_roundtrip(tmp_dir, samples)
        test_mask_and_strict_modes(tmp_dir, samples)
        test_cli(tmp_dir, samples)
        test_desktop_http_server(tmp_dir, samples)
        print("\n✓ 全部 5 组自动化回归测试通过！")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
