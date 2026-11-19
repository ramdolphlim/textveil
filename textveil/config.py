"""配置管理、规则预设与类别定义。"""

import copy
import json

CAT_NAMES = {
    "person": "姓名",
    "phone": "电话",
    "idcard": "身份证",
    "passport": "护照",
    "bankcard": "银行卡",
    "email": "邮箱",
    "address": "地址",
    "company": "企业机构",
    "uscc": "信用代码",
    "amount": "金额",
    "project": "项目合同",
    "bank_account": "对公账号",
    "api_key": "密钥凭证",
    "ip": "IP地址",
    "conn_str": "连接串",
    "internal_url": "内网路径",
    "keyword": "敏感词",
}

CAT_GROUPS = [
    ("pii", "个人隐私", ["person", "phone", "idcard", "passport", "bankcard", "email", "address"]),
    ("enterprise", "企业与商业", ["company", "uscc", "amount", "project", "bank_account"]),
    ("tech", "技术与凭证", ["api_key", "ip", "conn_str", "internal_url"]),
    ("custom", "自定义规则", ["keyword"]),
]

OPTION_INFO = [
    # 个人隐私 PII
    ("detect_phone", True, "个人隐私 PII", "手机号与固定电话（含区号/分机号）"),
    ("detect_idcard", True, "个人隐私 PII", "居民身份证号（18 位 GB 11643-1999 校验位验证）"),
    ("detect_passport", True, "个人隐私 PII", "护照与通行证号（结合标签上下文识别）"),
    ("detect_bankcard", True, "个人隐私 PII", "个人银行卡号（16-19 位 Luhn 算法校验）"),
    ("detect_email", True, "个人隐私 PII", "电子邮箱地址"),
    ("detect_person", True, "个人隐私 PII", "中文与英文姓名（标签旁、表格列与签名栏识别）"),
    ("detect_address", True, "个人隐私 PII", "详细通讯地址与住址（省市区 + 街道门牌）"),
    ("detect_author_in_body", True, "个人隐私 PII", "文档属性中的作者 / 经办人若出现在正文也一并脱敏"),
    # 企业与商业信息
    ("detect_company", True, "企业与商业信息", "中英文公司、集团、研究院、设计院、机构名称"),
    ("detect_uscc", True, "企业与商业信息", "统一社会信用代码（18 位 GB 32100-2015 校验位验证）"),
    ("detect_amount", True, "企业与商业信息", "明确标注币种或金额标签的合同金额与报价"),
    ("detect_project", True, "企业与商业信息", "项目名称、工程名称与合同 / 订单编号"),
    ("detect_bank_account", True, "企业与商业信息", "企业对公银行账号（结合账号/开户行上下文）"),
    # 技术凭证与密钥
    ("detect_api_key", True, "技术凭证与密钥", "API Key、Token、AK/SK、JWT、PEM 私钥与密码字段"),
    ("detect_ip", True, "技术凭证与密钥", "IPv4 / IPv6 地址（自动排除章节编号与版本号）"),
    ("detect_conn_str", True, "技术凭证与密钥", "数据库连接串（MySQL / PostgreSQL / Redis / MongoDB 等）"),
    ("detect_internal_url", True, "技术凭证与密钥", "内网域名 / 私网 URL 及本机用户目录路径（/Users/...、C:\\Users\\...）"),
    ("scan_code_blocks", True, "技术凭证与密钥", "扫描 Markdown / 文本代码块中的凭证、连接串与内网地址"),
    # 文档隐藏元数据
    ("clean_metadata", True, "文档隐藏元数据", "清理作者、公司、创建时间、XMP 与 YAML Frontmatter 等属性"),
    ("clean_comments", True, "文档隐藏元数据", "清除 Word / Excel / PPT / PDF 批注与注释作者"),
    ("clean_revisions", True, "文档隐藏元数据", "接受并清理 Word 修订记录（消除被删原文 <w:del> 与修改人）"),
    ("clean_hidden_sheets", False, "文档隐藏元数据", "直接删除 Excel 隐藏 / 深度隐藏工作表（关闭时仍会脱敏表内内容）"),
    ("clean_hyperlinks", True, "文档隐藏元数据", "脱敏或移除外部超链接中的敏感 URL 与 mailto 地址"),
    ("clean_thumbnails", True, "文档隐藏元数据", "移除文档内嵌缩略图（避免小图泄露首页版面信息）"),
]

META_ONLY_KEYS = {
    "clean_metadata",
    "clean_comments",
    "clean_revisions",
    "clean_hidden_sheets",
    "clean_hyperlinks",
    "clean_thumbnails",
}

PRESETS = [
    ("standard", "标准外发", "PII、企业商业、技术凭证与常见元数据"),
    ("ai", "AI 协作（可逆）", "全量识别并切换为可逆占位符，便于回填还原"),
    ("strict", "严格脱敏", "启用全部规则并删除隐藏工作表与全部附注"),
    ("meta", "仅清元数据", "仅清理作者、批注、修订记录、超链接与缩略图"),
]

DEFAULT_PSEUDONYMS = {
    "person": "[姓名_{n:02d}]",
    "phone": "[手机_{n:02d}]",
    "idcard": "[身份证_{n:02d}]",
    "passport": "[护照_{n:02d}]",
    "bankcard": "[银行卡_{n:02d}]",
    "email": "[邮箱_{n:02d}]",
    "address": "[地址_{n:02d}]",
    "company": "[企业_{n:02d}]",
    "uscc": "[信用代码_{n:02d}]",
    "amount": "[金额_{n:02d}]",
    "project": "[项目_{n:02d}]",
    "bank_account": "[对公账号_{n:02d}]",
    "api_key": "[密钥_{n:02d}]",
    "ip": "[IP_{n:02d}]",
    "conn_str": "[连接串_{n:02d}]",
    "internal_url": "[内网地址_{n:02d}]",
    "keyword": "[敏感词_{n:02d}]",
}

DEFAULT_WHITELIST = [
    "中华人民共和国",
    "国务院",
    "全国人民代表大会",
    "最高人民法院",
    "最高人民检察院",
    "国家标准",
    "中国标准出版社",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "example.com",
]

DEFAULT_CONFIG = {
    "mode": "placeholder",      # "placeholder" | "mask"
    "pdf_style": "replace",     # "replace" | "blackbox" (applies in mask mode or explicit choice)
    "preset": "standard",
    "options": {k: default for k, default, _, _ in OPTION_INFO},
    "keywords": [],
    "whitelist": list(DEFAULT_WHITELIST),
    "pseudonyms": dict(DEFAULT_PSEUDONYMS),
    "output_suffix": "_脱敏",
}


def preset_options(preset_name: str) -> dict:
    """根据预设名生成完整 options 字典。"""
    base = {k: default for k, default, _, _ in OPTION_INFO}
    if preset_name == "strict":
        return {k: True for k in base}
    if preset_name == "meta":
        return {k: (k in META_ONLY_KEYS) for k in base}
    if preset_name == "ai":
        return {k: (False if k == "clean_hidden_sheets" else True) for k in base}
    return base


def detect_preset(options: dict, mode: str = "") -> str:
    """判断当前规则开关属于哪个预设。"""
    keys = [k for k, _, _, _ in OPTION_INFO]
    if all(bool(options.get(k)) == (k in META_ONLY_KEYS) for k in keys):
        return "meta"
    if all(bool(options.get(k)) for k in keys):
        return "strict"
    std = preset_options("standard")
    if all(bool(options.get(k)) == bool(std[k]) for k in keys):
        return "ai" if mode == "placeholder" else "standard"
    ai_opts = preset_options("ai")
    if mode == "placeholder" and all(bool(options.get(k)) == bool(ai_opts[k]) for k in keys):
        return "ai"
    return "custom"


def merge_config(user_cfg=None) -> dict:
    """将用户配置与默认配置深度合并。"""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not user_cfg:
        return cfg
    if isinstance(user_cfg.get("mode"), str) and user_cfg["mode"] in ("placeholder", "mask"):
        cfg["mode"] = user_cfg["mode"]
    if isinstance(user_cfg.get("pdf_style"), str) and user_cfg["pdf_style"] in ("replace", "blackbox"):
        cfg["pdf_style"] = user_cfg["pdf_style"]
    if isinstance(user_cfg.get("preset"), str):
        cfg["preset"] = user_cfg["preset"]
    if isinstance(user_cfg.get("options"), dict):
        for k, v in user_cfg["options"].items():
            if k in cfg["options"]:
                cfg["options"][k] = bool(v)
    if isinstance(user_cfg.get("keywords"), list):
        cfg["keywords"] = [str(x).strip() for x in user_cfg["keywords"] if str(x).strip()]
    if isinstance(user_cfg.get("whitelist"), list):
        cfg["whitelist"] = [str(x).strip() for x in user_cfg["whitelist"] if str(x).strip()]
    if isinstance(user_cfg.get("pseudonyms"), dict):
        for k, v in user_cfg["pseudonyms"].items():
            if k in cfg["pseudonyms"] and isinstance(v, str) and v.strip():
                cfg["pseudonyms"][k] = v.strip()
    if isinstance(user_cfg.get("output_suffix"), str) and user_cfg["output_suffix"].strip():
        cfg["output_suffix"] = user_cfg["output_suffix"].strip()
    return cfg


def load_config(path: str) -> dict:
    """从 JSON 文件加载并合并配置。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return merge_config(data)
