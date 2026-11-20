#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
造价咨询类报告的识别回归测试（v1.0.1）。

用一份虚构的「跟踪审计竣工总结报告」复现这些情况（内容全部虚构）：
  1. 封面标题、「对XX项目（以下简称该项目）」里的项目名称，以及省略「项目」结尾的写法
  2. 业主公司全称 → 字号「云帆」被用作联系单编号前缀（云帆001、20250311云帆 …）
  3. 金额：正文「218,640,350元」、列头为「本期审核进度款（元）」「联系单审定增减额（元）」的表格列
  4. 不该被替换的：多列表格的表头、通用专业名称（土建总包工程）、百分比、「1615号」里的 615、「土建工程」里的「建工」
不需要 PyMuPDF。
"""
import glob
import os
import re
import shutil
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import docx  # noqa: E402

from textveil.config import merge_config  # noqa: E402
from textveil.pipeline import apply_pipeline, collect_files, restore_pipeline, scan_pipeline  # noqa: E402

PROJECT = "杭州云栖未来社区康养综合体项目"
OWNER = "杭州云帆康养管理有限公司"
CONTRACTOR = "杭州建工工程集团有限公司"


def make_report(path):
    d = docx.Document()
    d.add_paragraph(PROJECT)
    d.add_paragraph("跟踪审计（全过程造价咨询）竣工总结报告")
    d.add_paragraph("咨询单位：浙江明衡工程管理有限公司")
    d.add_paragraph("编制日期：2026年11月19日")
    d.add_paragraph(OWNER + "：")
    d.add_paragraph(f"我公司接受贵单位委托，自2022年3月起对{PROJECT}（以下简称该项目）提供全过程造价跟踪咨询服务。")
    d.add_heading("（一）土建总包工程", level=2)
    d.add_paragraph("三个专业原合同造价合计218,640,350元，联系单审定增减净额-1,305,722.46元，总体变动率-0.60%。")
    d.add_paragraph("开工初期（云帆001～035号）的联系单已在进度款中体现，表5自云帆036号起累计；另见共1615号文件。")
    d.add_paragraph(f"施工单位为{CONTRACTOR}，负责土建工程及安装工程。")

    t = d.add_table(rows=3, cols=5)
    for i, h in enumerate(["专业工程", "合同金额（元）", "联系单审定增减额（元）", "增减后金额（元）", "增减率"]):
        t.cell(0, i).text = h
    for i, v in enumerate(["土建总包工程", "196,420,800", "-1,104,318.25", "195,316,481.75", "-0.56%"]):
        t.cell(1, i).text = v
    for i, v in enumerate(["建筑幕墙（含门窗、泛光照明）工程", "22,219,550", "401,236", "22,620,786", "1.81%"]):
        t.cell(2, i).text = v

    t = d.add_table(rows=3, cols=5)
    for i, h in enumerate(["期次", "付款节点", "本期审核进度款（元）", "累计审核进度款（元）", "累计占合同价比率"]):
        t.cell(0, i).text = h
    for i, v in enumerate(["1", "桩基工程完成", "27,503,118.40", "27,503,118", "12.58%"]):
        t.cell(1, i).text = v
    for i, v in enumerate(["2", "底板完成", "31,088,420.15", "58,591,538", "26.80%"]):
        t.cell(2, i).text = v

    t = d.add_table(rows=3, cols=4)
    for i, h in enumerate(["序号", "联系单编号", "联系单名称", "审定金额（元）"]):
        t.cell(0, i).text = h
    for i, v in enumerate(["1", "云帆112", "20250311云帆 2#楼外窗型材调整联系单（建筑）", "615"]):
        t.cell(1, i).text = v
    for i, v in enumerate(["2", "云帆113", "20240917 杭州云栖未来社区康养综合体构造柱", "-352"]):
        t.cell(2, i).text = v

    t = d.add_table(rows=2, cols=2)  # 键值表：首行也是数据
    t.cell(0, 0).text, t.cell(0, 1).text = "联系人", "周子涵"
    t.cell(1, 0).text, t.cell(1, 1).text = "联系电话", "13700001111"
    d.save(path)


def doc_text(path):
    d = docx.Document(path)
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


def main():
    tmp = tempfile.mkdtemp(prefix="tv_rules_")
    try:
        src = os.path.join(tmp, "跟踪审计报告.docx")
        make_report(src)
        files = collect_files([src])
        cfg = merge_config()

        scan = scan_pipeline(files, cfg)
        terms = {t["term"]: t for t in scan["terms"]}
        assert PROJECT in terms and terms[PROJECT]["cat"] == "project", "封面 / 以下简称里的项目名称应被识别"
        assert "杭州云栖未来社区康养综合体" in terms, "省略「项目」结尾的项目名称应被识别"
        assert terms.get("云帆", {}).get("cat") == "company", "应由公司全称推断出字号「云帆」"
        assert "建工" not in terms, "「建工」是通用词，不应被当成字号"
        for amt in ("218,640,350", "-1,305,722.46", "-1,104,318.25", "401,236", "31,088,420.15", "27,503,118.40"):
            assert terms.get(amt, {}).get("cat") == "amount", "金额未识别：" + amt
        for wrong in ("合同金额（元）", "土建总包工程", "建筑幕墙（含门窗、泛光照明）工程", "桩基工程完成", "12.58%"):
            assert wrong not in terms, "不应被识别：" + wrong
        assert terms.get("周子涵", {}).get("cat") == "person", "键值表首行的人名应被识别"

        out = os.path.join(tmp, "out")
        res = apply_pipeline(files, out, cfg)
        assert res["ok"] == res["total"] == 1, res
        red = glob.glob(os.path.join(out, "**", "*.docx"), recursive=True)[0]
        txt = doc_text(red)
        for leak in ("云栖", "云帆", "康养综合体", "明衡", "周子涵", "218,640,350", "1,104,318", "31,088,420", "401,236"):
            assert leak not in txt, "脱敏后仍残留：" + leak
        for keep in ("合同金额（元）", "联系单审定增减额（元）", "累计占合同价比率", "土建总包工程", "桩基工程完成",
                     "12.58%", "-0.60%", "1615号", "土建工程及安装工程", "跟踪审计（全过程造价咨询）竣工总结报告"):
            assert keep in txt, "不该改动的内容被改了：" + keep
        assert re.search(r"\[企业_\d+\]112", txt), "联系单编号前缀应被替换"

        mp = glob.glob(os.path.join(out, "**", "映射表.json"), recursive=True)[0]
        back_dir = os.path.join(tmp, "back")
        rr = restore_pipeline(collect_files([red], skip_redacted=False), mp, back_dir, cfg)
        assert rr["ok"] == 1, rr
        back = glob.glob(os.path.join(back_dir, "**", "*.docx"), recursive=True)[0]
        assert doc_text(back) == doc_text(src), "还原后应与原文一致"
        print("报告识别规则测试通过：项目名称 / 字号推断 / 金额 / 表头与通用名称不误伤 / 还原一致")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
