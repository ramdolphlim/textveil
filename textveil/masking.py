"""双模式脱敏策略（可逆占位符 & 不可逆格式感知掩码）与映射表管理。"""

import json
import re
from .config import CAT_NAMES, DEFAULT_PSEUDONYMS


_COMPANY_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "科技有限公司",
    "有限公司",
    "分公司",
    "子公司",
    "设计研究院",
    "建筑设计院",
    "研究院",
    "设计院",
    "事务所",
    "咨询公司",
    "集团",
    "管委会",
    "委员会",
    "Co., Ltd.",
    "Co.,Ltd.",
    "Limited",
    "Ltd.",
    "Inc.",
    "Corp.",
    "Corporation",
    "LLC",
    "LLP",
    "GmbH",
)

_KEY_PREFIXES = (
    "github_pat_",
    "sk-ant-",
    "sk-proj-",
    "xoxb-",
    "xoxp-",
    "xoxa-",
    "xoxr-",
    "AKIA",
    "LTAI",
    "AKID",
    "AIza",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "sk-",
    "Bearer ",
)


def _has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def mask_value(term: str, cat: str) -> str:
    """根据敏感信息类别生成格式感知的不可逆掩码字符串。"""
    t = term.strip()
    if not t:
        return "****"

    if cat == "phone":
        digits = re.sub(r"\D", "", t)
        if "-" in t and len(digits) >= 7:
            head = t.split("-", 1)[0]
            return f"{head}-****{digits[-4:]}"
        if len(digits) >= 11:
            prefix = t[: len(t) - len(digits) + 3] if t.startswith("+") else digits[:3]
            return f"{prefix}****{digits[-4:]}"
        if len(digits) >= 7:
            return f"{digits[:3]}****{digits[-2:]}"
        return "***********"

    if cat == "idcard":
        if len(t) >= 15:
            return f"{t[:6]}{'*' * max(4, len(t) - 10)}{t[-4:]}"
        return "******************"

    if cat == "passport":
        if len(t) >= 6:
            return f"{t[0]}{'*' * (len(t) - 3)}{t[-2:]}"
        return "********"

    if cat in ("bankcard", "bank_account"):
        digits = re.sub(r"\D", "", t)
        if len(digits) >= 10:
            return f"{digits[:4]} {'*' * (len(digits) - 8)} {digits[-4:]}"
        if len(digits) >= 6:
            return f"{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"
        return "************"

    if cat == "email":
        if "@" in t:
            local, domain = t.split("@", 1)
            tld = domain.rsplit(".", 1)[-1] if "." in domain else "com"
            head = local[0] if local else "*"
            return f"{head}***@***.{tld}"
        return "***@***.com"

    if cat == "person":
        compact = re.sub(r"[\s\u3000]+", "", t)
        if _has_cjk(compact):
            if len(compact) <= 2:
                return f"{compact[0]}*"
            return f"{compact[0]}{'*' * (len(compact) - 1)}"
        parts = t.split()
        if len(parts) >= 2:
            return " ".join(p[0] + "***" for p in parts if p)
        return f"{t[0]}***"

    if cat == "address":
        if len(t) >= 10:
            # 只保留最多前 3 字（如省/市头），其余全部打码
            m = re.match(r"^([\u4e00-\u9fff]{2,3}(?:省|市))", t)
            prefix = m.group(1) if m else t[:3]
            return f"{prefix}********"
        return "********"

    if cat == "company":
        for suf in _COMPANY_SUFFIXES:
            if t.lower().endswith(suf.lower()):
                actual_suf = t[len(t) - len(suf) :]
                if _has_cjk(actual_suf):
                    return f"某****{actual_suf}"
                return f"**** {actual_suf}"
        return "某****单位" if _has_cjk(t) else "**** Corp."

    if cat == "uscc":
        return f"{t[:2]}{'*' * max(8, len(t) - 2)}"

    if cat == "amount":
        # 保留币种和单位，数字及大写数字全替换为 *
        masked = re.sub(r"[0-9]", "*", t)
        masked = re.sub(r"[壹贰叁肆伍陆柒捌玖拾佰仟万亿零]", "*", masked)
        if "*" not in masked:
            return "***"
        return masked

    if cat == "project":
        if re.fullmatch(r"[A-Za-z0-9_\-/]+", t):
            return f"{t[:2]}***" if len(t) > 4 else "***"
        return "某***项目"

    if cat == "api_key":
        if "BEGIN" in t and "PRIVATE KEY" in t:
            return "[REDACTED PRIVATE KEY]"
        # 键=值形式保留键名
        kv = re.match(r"^([A-Za-z0-9_\-\u4e00-\u9fff]+\s*[:=]\s*['\"]?)(.+?)(['\"]?)$", t)
        if kv:
            return f"{kv.group(1)}************{kv.group(3)}"
        for pfx in _KEY_PREFIXES:
            if t.startswith(pfx):
                return f"{pfx}************"
        if len(t) > 8:
            return f"{t[:4]}************"
        return "************"

    if cat == "ip":
        if ":" in t:
            return "****:****:****"
        return "***.***.***.***"

    if cat == "conn_str":
        m = re.match(r"^([a-zA-Z0-9+._-]+://)", t)
        if m:
            return f"{m.group(1)}***:***@***"
        return "[已脱敏连接串]"

    if cat == "internal_url":
        if t.startswith("/Users/") or t.startswith("/home/"):
            parts = t.split("/", 3)
            if len(parts) >= 3:
                return f"/{parts[1]}/***" + (f"/{parts[3]}" if len(parts) > 3 else "")
        if re.match(r"^[A-Za-z]:\\Users\\", t, re.I):
            return re.sub(r"^([A-Za-z]:\\Users\\)[^\\]+", r"\1***", t)
        return "[已脱敏内网地址]"

    # 自定义敏感词等
    return "****"


def _format_placeholder(template: str, idx: int, cat: str) -> str:
    try:
        return template.format(n=idx)
    except Exception:
        label = CAT_NAMES.get(cat, "敏感词")
        return f"[{label}_{idx:02d}]"


def _next_placeholder(cat: str, counters: dict, used_codes: set, cfg: dict) -> str:
    tpl = (cfg.get("pseudonyms") or {}).get(cat) or DEFAULT_PSEUDONYMS.get(cat, "[敏感词_{n:02d}]")
    n = counters.get(cat, 0) + 1
    while True:
        code = _format_placeholder(tpl, n, cat)
        if code not in used_codes:
            counters[cat] = n
            used_codes.add(code)
            return code
        n += 1


def _parse_existing_index(code: str, cat: str, cfg: dict) -> int:
    tpl = (cfg.get("pseudonyms") or {}).get(cat) or DEFAULT_PSEUDONYMS.get(cat, "[敏感词_{n:02d}]")
    # 把 {n...} 替换成数字捕获组
    pat = re.escape(tpl)
    pat = re.sub(r"\\\{n[^}]*\\\}", r"(\\d+)", pat)
    m = re.fullmatch(pat, code)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    m2 = re.search(r"(\d+)", code)
    return int(m2.group(1)) if m2 else 0


def build_mapping(findings, cfg: dict, decisions=None, previous=None) -> dict:
    """
    构建统一脱敏映射：
    - 每条保留 placeholder_replace（可逆占位符）与 mask_replace（掩码）
    - active replace 按 cfg['mode'] 及 decisions 覆盖决定
    - previous 支持跨批次复用历史映射中的编号与替换值
    """
    decisions = decisions or {}
    mode = cfg.get("mode", "placeholder")
    prev_by_term = {}
    counters = {}
    used_codes = set()

    if previous:
        prev_entries = previous.get("entries") if isinstance(previous, dict) else previous
        if isinstance(prev_entries, list):
            for e in prev_entries:
                term = e.get("term")
                if not term:
                    continue
                prev_by_term[term] = e
                ph = e.get("placeholder_replace") or (e.get("replace") if e.get("mode") == "placeholder" else "")
                if ph:
                    used_codes.add(ph)
                    cat = e.get("cat", "keyword")
                    idx = _parse_existing_index(ph, cat, cfg)
                    if idx > counters.get(cat, 0):
                        counters[cat] = idx

    entries = []
    # 按类别和出现频次稳定排序，保证占位符序号可预测
    ordered = sorted(
        findings.items.values(),
        key=lambda item: (-item.count, item.cat, item.term),
    )

    for item in ordered:
        term = item.term
        cat = item.cat
        prev = prev_by_term.get(term)
        dec = decisions.get(term) or {}

        if item.custom_replace:
            ph_code = item.custom_replace
            mk_code = item.custom_replace
        else:
            if prev and prev.get("placeholder_replace"):
                ph_code = prev["placeholder_replace"]
            else:
                ph_code = _next_placeholder(cat, counters, used_codes, cfg)
            mk_code = (prev.get("mask_replace") if prev else None) or mask_value(term, cat)

        enabled = item.enabled
        if "enabled" in dec:
            enabled = bool(dec["enabled"])

        default_rep = ph_code if mode == "placeholder" else mk_code
        custom_rep = dec.get("replace")
        if isinstance(custom_rep, str) and custom_rep != "" and dec.get("edited"):
            active_rep = custom_rep
        elif isinstance(custom_rep, str) and custom_rep != "" and "edited" not in dec:
            # 来自命令行或外部明确指定的替换词
            active_rep = custom_rep
        else:
            active_rep = default_rep

        entries.append(
            {
                "term": term,
                "cat": cat,
                "cat_name": CAT_NAMES.get(cat, cat),
                "rule": item.rule,
                "count": item.count,
                "files": sorted(item.files),
                "samples": list(item.samples),
                "enabled": enabled,
                "replace": active_rep,
                "placeholder_replace": ph_code,
                "mask_replace": mk_code,
                "custom_replace": item.custom_replace,
                "warn": item.warn,
            }
        )

    return {
        "mode": mode,
        "entries": entries,
    }


def mapping_regex(mapping: dict, only_enabled: bool = True):
    """编译按原文长度降序排列的正则（避免短词抢先截断长词）。"""
    entries = mapping.get("entries", []) if isinstance(mapping, dict) else mapping
    terms = [e["term"] for e in entries if (not only_enabled or e.get("enabled", True)) and e.get("term")]
    if not terms:
        return None
    # 去重后按长度降序
    uniq = sorted(set(terms), key=len, reverse=True)
    pattern = "|".join(re.escape(t) for t in uniq)
    return re.compile(pattern)


def active_replace_map(mapping: dict) -> dict:
    """返回 {原文: 替换文本} 字典（仅含启用项）。"""
    entries = mapping.get("entries", []) if isinstance(mapping, dict) else mapping
    out = {}
    for e in entries:
        if e.get("enabled", True) and e.get("term"):
            out[e["term"]] = e.get("replace", "")
    return out


def mapping_export(mapping: dict) -> dict:
    """生成可序列化保存的映射表结构。"""
    entries = mapping.get("entries", []) if isinstance(mapping, dict) else mapping
    return {
        "tool": "TextVeil",
        "mode": mapping.get("mode", "placeholder") if isinstance(mapping, dict) else "placeholder",
        "entries": [
            {
                "term": e["term"],
                "cat": e["cat"],
                "cat_name": e.get("cat_name") or CAT_NAMES.get(e["cat"], e["cat"]),
                "rule": e.get("rule", ""),
                "replace": e["replace"],
                "placeholder_replace": e.get("placeholder_replace", e["replace"]),
                "mask_replace": e.get("mask_replace", ""),
                "enabled": e.get("enabled", True),
                "count": e.get("count", 1),
                "files": e.get("files", []),
            }
            for e in entries
        ],
    }


def load_mapping_file(path: str) -> dict:
    """读取 JSON 映射表（兼容 dict 或 list）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"mode": "placeholder", "entries": data}
    if isinstance(data, dict) and "entries" in data:
        return data
    if isinstance(data, dict) and "mapping" in data:
        return {"mode": data.get("mode", "placeholder"), "entries": data["mapping"]}
    raise ValueError("无法识别的映射表文件格式，请确认选择了 TextVeil 生成的 映射表.json")


def build_inverse_mapping(mapping_data) -> tuple[dict, list]:
    """
    从映射表构建反向还原字典 {替换后文本: 原文}，并返回告警信息列表。
    对于多对一碰撞（如掩码模式的 ****）会发出明确警示。
    """
    entries = mapping_data.get("entries", []) if isinstance(mapping_data, dict) else mapping_data
    inv = {}
    collisions = {}
    warnings = []

    for e in entries:
        if not e.get("enabled", True):
            continue
        term = e.get("term", "")
        rep = e.get("replace", "")
        if not term or not rep or term == rep:
            continue
        if rep in inv and inv[rep] != term:
            collisions.setdefault(rep, {inv[rep]}).add(term)
        else:
            inv[rep] = term

    for rep, terms in collisions.items():
        inv.pop(rep, None)
        warnings.append(
            f"替换值「{rep}」对应 {len(terms)} 个不同原文（不可逆掩码无法唯一还原，已跳过）"
        )

    if not inv and not warnings:
        warnings.append("映射表中没有可还原的条目（请确认使用的是可逆占位符模式生成的映射表）")

    return inv, warnings


def inverse_regex(inv_map: dict):
    """为还原阶段编译按替换值长度降序的正则。"""
    if not inv_map:
        return None
    keys = sorted(inv_map.keys(), key=len, reverse=True)
    return re.compile("|".join(re.escape(k) for k in keys))
