"""统一敏感信息识别器（PII / 企业商业 / 技术凭证 / 自定义词库与表格上下文）。"""

import ipaddress
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 校验位与合法性验证
# ---------------------------------------------------------------------------

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CODES = "10X98765432"
_PROVINCE_PREFIXES = {
    "11", "12", "13", "14", "15",
    "21", "22", "23",
    "31", "32", "33", "34", "35", "36", "37",
    "41", "42", "43", "44", "45", "46",
    "50", "51", "52", "53", "54",
    "61", "62", "63", "64", "65",
    "71", "81", "82",
}


def idcard_ok(s: str) -> bool:
    """校验 18 位中华人民共和国居民身份证号（GB 11643-1999）。"""
    s = s.strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", s):
        return False
    if s[:2] not in _PROVINCE_PREFIXES:
        return False
    year = int(s[6:10])
    month = int(s[10:12])
    day = int(s[12:14])
    if not (1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31):
        return False
    if month in (4, 6, 9, 11) and day > 30:
        return False
    if month == 2 and day > 29:
        return False
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CODES[total % 11] == s[17]


_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def uscc_ok(s: str) -> bool:
    """校验 18 位统一社会信用代码（GB 32100-2015）。"""
    s = s.strip().upper()
    if len(s) != 18:
        return False
    if s[0] not in "159Y":
        return False
    if not all(c in _USCC_CHARS for c in s):
        return False
    total = sum(_USCC_CHARS.index(s[i]) * _USCC_WEIGHTS[i] for i in range(17))
    check = (31 - (total % 31)) % 31
    return _USCC_CHARS[check] == s[17]


def luhn_ok(digits: str) -> bool:
    """校验 16-19 位银行卡号 Luhn 校验和。"""
    if not digits.isdigit() or not (16 <= len(digits) <= 19):
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    rev = digits[::-1]
    for i, ch in enumerate(rev):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def ipv4_ok(s: str, prefix_ctx: str = "", suffix_ctx: str = "") -> bool:
    """校验 IPv4 并排除常见版本号/文档章节编号误报。"""
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit():
            return False
        if len(p) > 1 and p.startswith("0"):
            return False
        if int(p) > 255:
            return False
    # 排除紧跟在 v/V/Ver/第 后面的版本号
    if re.search(r"(?:[vV]|ver\.?|version|第)\s*$", prefix_ctx, re.I):
        return False
    # 纯 0.x.x.x 或 1.2.3.4 章节号（无端口/URL/IP语境）谨慎判断
    first = int(parts[0])
    if first == 0:
        return False
    has_ip_ctx = bool(
        re.search(r"(?:ip|host|server|addr|ssh|tcp|udp|http|https|://|@|节点|服务器|网关|内网|地址)\s*[:：=]?\s*$", prefix_ctx, re.I)
        or re.match(r"^(?::\d{1,5}|/\d{1,2})", suffix_ctx)
    )
    if not has_ip_ctx and first <= 9 and int(parts[1]) <= 20 and int(parts[2]) <= 30 and int(parts[3]) <= 30:
        # 形如 1.1.1.1 之外的小数字段落 1.2.3.4 容易是章节号，私有段 10.x 除外
        return False
    return True


# ---------------------------------------------------------------------------
# 姓氏表与中文人名判断
# ---------------------------------------------------------------------------

_SINGLE_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍晁勾敖融冷訾辛阚那简饶空曾"
    "毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公万俟司马上官欧阳夏侯"
    "诸葛闻人东方赫连皇甫尉迟公羊澹台公冶宗政濮阳淳于单于太叔申屠公孙"
    "仲孙轩辕令狐钟离宇文长孙慕容鲜于闾丘司徒司空亓官司寇仉督子车颛孙"
    "端木巫马公西漆雕乐正壤驷公良拓跋夹谷宰父谷梁晋楚闫法汝鄢涂钦段干"
    "百里东郭南门呼延归海羊舌微生岳帅缑亢况后有琴梁丘左丘东门西门商牟"
    "佘佴伯赏南宫墨哈谯笪年爱阳佟第五言福"
)

_DOUBLE_SURNAMES = (
    "欧阳", "司马", "上官", "诸葛", "端木", "皇甫", "慕容", "公孙",
    "夏侯", "东方", "南宫", "西门", "尉迟", "长孙", "宇文", "令狐",
    "司徒", "司空", "鲜于", "百里", "东郭", "呼延", "钟离", "申屠",
)

_NAME_STOP_WORDS = {
    "无", "暂无", "待定", "待补", "空白", "略", "不详", "未知", "默认",
    "合计", "小计", "总计", "汇总", "备注", "说明", "日期", "时间",
    "签字", "签名", "盖章", "公章", "单位", "公司", "机构", "部门",
    "地址", "电话", "手机", "邮箱", "传真", "网址", "编号", "序号",
    "项目", "工程", "合同", "金额", "价格", "报价", "数量", "规格",
    "型号", "状态", "结果", "正常", "通过", "完成", "失败", "错误",
    "测试", "示例", "样例", "模板", "甲方", "乙方", "丙方", "丁方",
    "先生", "女士", "同志", "经理", "总监", "主任", "院长", "部长",
    "主管", "代表", "本人", "自己", "对方", "客户", "供应商", "联系人",
    "负责人", "经办人", "审核人", "审批人", "制表人", "复核人", "创建人",
    "人员", "员工", "用户", "管理员", "开发者", "系统", "平台", "服务",
    "中国", "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉",
    "南京", "苏州", "天津", "重庆", "西安", "长沙", "郑州", "青岛",
    "人民币", "美元", "欧元", "万元", "亿元", "合同额", "总价",
}


def name_like(s: str) -> bool:
    """判断字符串是否像一个合法中文或英文人名。"""
    t = re.sub(r"[\s\u3000]+", "", s or "").strip()
    if not t or t in _NAME_STOP_WORDS:
        return False
    # 纯中文 2-4 字且首字（或复姓）在姓氏表中
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", t):
        if any(w in t for w in ("公司", "有限", "集团", "部门", "中心", "医院", "学校", "学院", "设计", "工程", "项目", "合同", "信息", "数据")):
            return False
        if len(t) >= 3 and t[:2] in _DOUBLE_SURNAMES:
            return True
        if len(t) <= 3 and t[0] in _SINGLE_SURNAMES:
            return True
        return False
    # 英文人名（2-3 单词，首字母大写，如 John Doe / Alice Wang）
    raw = (s or "").strip()
    if re.fullmatch(r"[A-Z][a-z]{1,18}(?:\s+[A-Z][a-z]{1,18}){1,2}", raw):
        if raw.lower() not in {"project name", "company name", "not applicable", "to be determined"}:
            return True
    return False


# ---------------------------------------------------------------------------
# Finding 数据结构
# ---------------------------------------------------------------------------

@dataclass
class FindingItem:
    term: str
    cat: str
    rule: str
    count: int = 0
    files: set = field(default_factory=set)
    samples: list = field(default_factory=list)
    enabled: bool = True
    custom_replace: str = ""
    warn: str = ""


class Findings:
    """聚合多文档扫描到的敏感词条目。"""

    def __init__(self):
        self.items: dict[str, FindingItem] = {}

    def add(
        self,
        term: str,
        cat: str,
        rule: str,
        fname: str,
        sample: str = "",
        custom_replace: str = "",
        warn: str = "",
    ):
        term = (term or "").strip()
        if not term:
            return
        if term not in self.items:
            self.items[term] = FindingItem(
                term=term,
                cat=cat,
                rule=rule,
                custom_replace=custom_replace,
                warn=warn,
            )
        it = self.items[term]
        it.count += 1
        if fname:
            it.files.add(fname)
        if custom_replace and not it.custom_replace:
            it.custom_replace = custom_replace
        if sample and len(it.samples) < 3:
            clean_s = re.sub(r"\s+", " ", sample).strip()[:80]
            if clean_s and clean_s not in it.samples:
                it.samples.append(clean_s)


# ---------------------------------------------------------------------------
# 正则与规则定义
# ---------------------------------------------------------------------------

class CustomRule:
    def __init__(self, raw: str):
        self.raw = raw
        self.replace = ""
        self.is_regex = False
        body = raw.strip()
        if "=" in body and not body.startswith("re:"):
            left, right = body.split("=", 1)
            body = left.strip()
            self.replace = right.strip()
        elif body.startswith("re:"):
            # 支持 re:pattern=replace（仅当尾部 = 后不像正则内部符号时切分）
            rest = body[3:]
            if "=" in rest and not re.search(r"\[[^\]]*=[^\]]*\]|\(\?<=", rest):
                left, right = rest.rsplit("=", 1)
                if left.strip():
                    rest, self.replace = left.strip(), right.strip()
            body = rest
            self.is_regex = True

        self.pattern_text = body
        if self.is_regex:
            try:
                self.regex = re.compile(body)
            except re.error:
                self.regex = re.compile(re.escape(body))
        else:
            self.regex = re.compile(re.escape(body)) if body else None


def parse_keywords(items: list) -> list[CustomRule]:
    out = []
    for raw in items or []:
        s = str(raw).strip()
        if not s:
            continue
        r = CustomRule(s)
        if r.regex is not None and r.pattern_text:
            out.append(r)
    return out


# 技术凭证与密钥
_RE_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]{10,}?-----END [A-Z0-9 ]*PRIVATE KEY-----")
_RE_JWT = re.compile(r"(?<![A-Za-z0-9_-])(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_-])")
_RE_KNOWN_KEY = re.compile(
    r"(?<![A-Za-z0-9_-])("
    r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9_]{16,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"LTAI[A-Za-z0-9]{12,24}|"
    r"AKID[A-Za-z0-9]{20,40}|"
    r"xox[baprs]-[0-9A-Za-z-]{12,}|"
    r"AIza[0-9A-Za-z_-]{30,}"
    r")(?![A-Za-z0-9_-])"
)
_RE_KV_SECRET = re.compile(
    r"(?:^|[\s,;\"'(])"
    r"((?:api[_-]?key|access[_-]?key(?:_id|_secret)?|secret[_-]?key|app[_-]?secret|client[_-]?secret|"
    r"private[_-]?key|auth[_-]?token|access[_-]?token|bearer|password|passwd|pwd|db_pass|"
    r"密钥|访问密钥|私钥|密码|口令)"
    r"\s*[:=：]\s*['\"]?([A-Za-z0-9_./+=@!#$%^&*-]{6,80})['\"]?)",
    re.I,
)
_RE_CONN_STR = re.compile(
    r"(?<![A-Za-z0-9])((?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis|rediss|amqp|amqps|jdbc:[a-z0-9]+|mssql|oracle|clickhouse)"
    r"://[^\s'\"<>)\]]{6,})",
    re.I,
)
_RE_INTERNAL_URL = re.compile(
    r"https?://(?:"
    r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})"
    r"|[a-zA-Z0-9.-]+\.(?:internal|local|corp|lan|intranet|oa|intra)"
    r")(?::\d{1,5})?(?:/[^\s'\"<>)\]]*)?",
    re.I,
)
_RE_LOCAL_PATH = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+(?:/[^\s'\"<>)\],;，。；]+)*|"
    r"/home/[A-Za-z0-9._-]+(?:/[^\s'\"<>)\],;，。；]+)*|"
    r"[A-Za-z]:\\Users\\[^\\\s'\"<>]+(?:\\[^\s'\"<>)\],;，。；]+)*)"
)
_RE_IPV4 = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
_RE_IPV6 = re.compile(r"(?<![A-Za-z0-9:])((?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4})(?![A-Za-z0-9:])")

# PII 正则
_RE_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,12})(?![A-Za-z0-9])")
_RE_IDCARD = re.compile(r"(?<![\dA-Za-z])([1-8]\d{16}[\dXx])(?![\dA-Za-z])")
_RE_USCC = re.compile(r"(?<![0-9A-Za-z])([159Y][0-9A-HJ-NPQRTUWXY]{17})(?![0-9A-Za-z])")
_RE_MOBILE = re.compile(r"(?<!\d)((?:\+?86[-\s]?)?1[3-9]\d{9})(?!\d)")
_RE_LANDLINE = re.compile(r"(?<!\d)(0\d{2,3}-\d{7,8}(?:-\d{1,5})?)(?!\d)")
_RE_BANK_DIGITS = re.compile(r"(?<!\d)(\d{4}(?:[ -]?\d{4}){3,4})(?!\d)")
_RE_PASSPORT = re.compile(
    r"(?:护照(?:号|号码)?|Passport(?:\s*No\.?)?)\s*[:：]?\s*([EeGgDdPpSs]\d{8}|1[45]\d{7})(?![A-Za-z0-9])",
    re.I,
)

# 中文 / 英文单位名称（非贪婪避免跨连词合并多家公司）
_RE_CN_COMPANY = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9（）()·]{2,28}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|科技有限公司|信息技术有限公司|咨询有限公司|"
    r"有限公司|分公司|设计研究院|建筑设计院|研究院|设计院|事务所))"
)
_RE_EN_COMPANY = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9&.,'\- ]{2,45}\s+(?:Co\.,\s*Ltd\.|Co\.,Ltd\.|Limited|Ltd\.|Inc\.|Corp\.|Corporation|LLC|LLP|GmbH))"
)

_CN_COMPANY_PREFIX_NOISE = re.compile(
    r"^(?:.*?(?:本协议由|本系统由|本项目由|本合同由|本方案由|委托方为|受托方为|甲方为|乙方为|建设单位为|"
    r"请[^\s，。；：]{1,4}核对|由|与|和|及|跟|同|被|将|把|经|对|在|到|从|自|至|为|关于|委托|授权|"
    r"甲方|乙方|丙方|丁方|建设单位|设计单位|施工单位|监理单位|服务商|供应商|承建方|采购方|"
    r"开户行|收款方|付款方|签署|签订|核对|确认|公司名称|单位名称|企业名称|名称|是|系|[:：\s、，。；()])+)"
)

# 地址
_RE_ADDRESS = re.compile(
    r"((?:[\u4e00-\u9fff]{2,5}(?:省|自治区|市))?"
    r"(?:[\u4e00-\u9fff]{2,6}(?:市|区|县|旗))+"
    r"(?:[\u4e00-\u9fff]{1,10}(?:街道|镇|乡|路|街|大道|巷|弄|胡同))"
    r"[\u4e00-\u9fffA-Za-z0-9\-号楼栋单元室座层广场大厦园区]{2,26})"
)
_ADDR_PREFIX_NOISE = re.compile(r"^(?:[\u4e00-\u9fff]{0,6}(?:办公|联系|通讯|注册|收货)?地址(?:位于)?[:：\s]*|公地址位于|位于|坐落于|在)")

# 金额（明确带有币种/金额前缀或单位）
_RE_AMOUNT_CURRENCY = re.compile(
    r"(?:(?:¥|￥|\$|RMB|CNY|USD|EUR|人民币|美元|港币)\s*[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?(?:\s*[万亿千]?元)?|"
    r"[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?\s*(?:万元|亿元|万人民币|万美元))"
)

# 行内标签提取：标签 -> (类别, 规则描述)
_INLINE_LABELS = [
    (r"(?:(?:项目|技术|内部|保密|紧急|现场|主要)?(?:姓名|联系人|负责人|经办人|签署人|法定代表人|法人代表|法人|项目经理|审核人|批准人|创建人|作者|设计师|制图人|收件人|发件人|开户名|户名))", "person", "行内标签"),
    (r"(?:甲方|乙方|丙方|丁方|委托方|受托方|建设单位|承建单位|施工单位|设计单位|采购方|供应商|服务商|客户名称|公司名称|单位名称|开户银行|开户行)", "company", "行内标签"),
    (r"(?:项目名称|工程名称|项目编号|工程编号|合同编号|订单编号|采购编号|标段名称)", "project", "行内标签"),
    (r"(?:收款账号|银行账号|对公账号|汇款账号|账户号码|账号)", "bank_account", "行内标签"),
    (r"(?:通讯地址|联系地址|注册地址|办公地址|详细地址|收货地址|住址|地址)", "address", "行内标签"),
    (r"(?:合同金额|合同总价|项目总价|中标金额|报价金额|总金额|含税金额|成交金额|金额)", "amount", "行内标签"),
]

_INLINE_STOP_CHARS = r"\n\r\t|｜；;。·•"

# 表格列头映射
_HEADER_CATS = [
    (re.compile(r"姓名|联系人|负责人|经办人|签字|签名|法人|作者|员工|成员|客户经理", re.I), "person"),
    (re.compile(r"手机|电话|联系方式|座机|传真|tel|phone|mobile", re.I), "phone"),
    (re.compile(r"邮箱|电邮|email|e-mail|mail", re.I), "email"),
    (re.compile(r"身份证|证件号|id\s*card|identity", re.I), "idcard"),
    (re.compile(r"护照|passport", re.I), "passport"),
    (re.compile(r"银行卡|卡号|card\s*no", re.I), "bankcard"),
    (re.compile(r"对公账号|银行账号|收款账号|账号|account", re.I), "bank_account"),
    (re.compile(r"公司|单位|企业|机构|甲方|乙方|供应商|客户名|company|org", re.I), "company"),
    (re.compile(r"统一社会信用|信用代码|税号|uscc", re.I), "uscc"),
    (re.compile(r"地址|住址|address|location", re.I), "address"),
    (re.compile(r"项目|工程|合同号|合同编号|project|contract", re.I), "project"),
    (re.compile(r"金额|报价|总价|单价|薪资|工资|奖金|预算|[（(]万?元[）)]|进度款|增减额|审定额|核减额|价款|造价|结算价|费用|税额|amount|price|salary", re.I), "amount"),
    (re.compile(r"密码|口令|密钥|token|secret|api.?key|password|pwd", re.I), "api_key"),
    (re.compile(r"\bip\b|ip地址|主机地址|服务器", re.I), "ip"),
]


def classify_header(header: str):
    h = (header or "").strip()
    if not h or len(h) > 24:
        return None
    for pat, cat in _HEADER_CATS:
        if pat.search(h):
            if cat == "amount" and _RE_RATIO_HEADER.search(h):
                return None  # 「累计占合同价比率」「增减率」这类是百分比，不是金额
            return cat
    return None


def _clean_cn_company(s: str) -> str:
    s = s.strip()
    prev = None
    while prev != s:
        prev = s
        s = _CN_COMPANY_PREFIX_NOISE.sub("", s).strip()
    if len(s) < 4:
        return ""
    # 不允许只是泛称
    if s in {"有限责任公司", "股份有限公司", "有限公司", "分公司", "研究院", "设计院", "集团有限公司"}:
        return ""
    return s


_RE_RATIO_HEADER = re.compile(r"率|比例|占比|百分|%|％")

# 正文里「数字 + 元」形式的金额（带千分位，或不少于 4 位整数），只取数字部分，便于和表格里的同一金额共用代号
_RE_AMOUNT_YUAN = re.compile(r"(?<![\d.,，])([-−]?\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?|[-−]?\d{4,}(?:\.\d{1,4})?)(?=\s*元)")

# 「XXX（以下简称“YYY”）」：XXX 是被定义的名称（项目 / 单位），YYY 是它的简称
_RE_ALIAS_DEF = re.compile(
    r"([^\s，。；;：:、,“”\"《》〈〉（）()\[\]【】]{2,60})\s*[（(]\s*(?:以下|下文|下称|以下均)?\s*(?:简称|称为|称)\s*[：:]?\s*"
    r"[“\"「『‘]?([^”\"」』’）),，、\s]{1,20}?)[”\"」』’]?\s*[）)]"
)
_ALIAS_GENERIC = {
    "项目", "工程", "本项目", "该项目", "本工程", "该工程", "合同", "本合同", "协议", "本协议", "公司", "本公司", "集团",
    "甲方", "乙方", "丙方", "丁方", "发包人", "承包人", "发包方", "承包方", "业主", "建设单位", "委托人", "受托人",
    "委托方", "受托方", "咨询人", "监理人", "设计人", "招标人", "投标人", "中标人", "采购人", "供应商", "我方", "对方",
}
_RE_NAME_PREFIX_NOISE = re.compile(
    r"^(?:[^一-鿿A-Za-z]+|自[^对就为在]{0,12}?起|我公司|本公司|我单位|贵单位|贵公司|贵方|接受|委托|"
    r"针对|关于|对于|对|就|为|在|由|受|向|将|把|是|系|即|经|按|根据|依据|承接|承建|负责|参与|完成|开展|做好|实施)+"
)
_RE_PROJECT_END = re.compile(r"(?:项目|工程|标段|[一二三四五六七八九十\d]期)$")
_RE_COMPANY_END = re.compile(r"(?:有限责任公司|股份有限公司|有限公司|分公司|集团|研究院|设计院|事务所|公司)$")

# 只由这些「通用专业 / 工程类别」词组成的名称不算具体项目（如「土建总包工程」「市政及景观工程」）
_RE_GENERIC_ENG = re.compile(
    r"总承包|总包|土建|安装|市政|景观|幕墙|门窗|泛光|照明|给排水|给水|排水|电气|暖通|空调|通风|消防|智能化|弱电|强电|机电|"
    r"装饰|装修|精装|绿化|园林|钢结构|结构|桩基|基坑|支护|土方|室外|室内|道路|管网|人防|建筑|主体|附属|配套|专业|分包|劳务|"
    r"材料|设备|工程|项目|改造|新建|扩建|维修|修缮|零星|临时|设施|系统|其他|其它|单位|分部|分项|子|含|及|和|与|等|"
    r"第?[一二三四五六七八九十\d]+(?:标段|期)|标段|[、（）()\s\d#\-·.]"
)
_RE_HEADING_ENUM = re.compile(r"^(?:[（(][一二三四五六七八九十\d]{1,3}[）)]|[一二三四五六七八九十]{1,3}、|\d+(?:\.\d+)*[、.．\s]|第[一二三四五六七八九十\d]+[章节条])")
_RE_TITLE_TAIL = re.compile(
    r"(?=跟踪审计|全过程|竣工|结算|预算|概算|估算|招标|投标|施工|造价|审核|审计|咨询|可行性|设计|监理|总结|报告|方案|合同|"
    r"技术|实施|建议书|进度|周报|月报|例会|会议纪要|工程量|清单|评估|验收|计划)"
)


def project_specific(name: str) -> bool:
    """去掉通用专业词后还剩专有名称（地名、单位名、楼盘名等）才算具体项目。"""
    return len(_RE_GENERIC_ENG.sub("", name or "")) >= 2


def _clean_name_prefix(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = _RE_NAME_PREFIX_NOISE.sub("", s).strip()
    return s


# 由公司全称推断常用简称（如 杭州云帆康养管理有限公司 → 云帆），用于识别「云帆086」这类编号和简称
_RE_REGION_PREFIX = re.compile(
    r"^(?:中国|中华|"
    r"北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|"
    r"陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门|"
    r"杭州|宁波|温州|绍兴|嘉兴|湖州|金华|台州|丽水|衢州|舟山|义乌|慈溪|余姚|萧山|余杭|南京|苏州|无锡|常州|南通|扬州|"
    r"镇江|徐州|盐城|泰州|昆山|合肥|芜湖|福州|厦门|泉州|南昌|济南|青岛|烟台|郑州|武汉|长沙|广州|深圳|佛山|东莞|珠海|中山|"
    r"成都|贵阳|昆明|西安|兰州|沈阳|大连|长春|哈尔滨|石家庄|太原|南宁|海口|三亚|乌鲁木齐|呼和浩特|银川|西宁|拉萨)"
    r"(?:省|市|区|县|自治区|特别行政区)?"
)
_RE_COMPANY_SUFFIX = re.compile(r"(?:股份有限公司|有限责任公司|集团有限公司|有限公司|分公司|集团|公司|研究院|设计院|事务所)$")
_RE_INDUSTRY_SUFFIX = re.compile(
    r"(?:健康管理|工程管理|项目管理|企业管理|物业管理|资产管理|投资管理|全过程工程咨询|工程咨询|造价咨询|管理咨询|信息技术|"
    r"勘察设计|建筑设计|房地产开发|供应链|科技|技术|网络|软件|数据|智能|咨询|建设|建筑|工程|设计|勘察|综合|研究|置业|"
    r"房地产|开发|投资|实业|贸易|商贸|发展|控股|服务|医疗|健康|养老|教育|文化|传媒|环境|环保|能源|电力|电子|机械|制造|"
    r"材料|物流|建工|路桥|交通|水利|市政|园林|装饰|劳务|安装|机电|电气|消防|管理|国际|股份|"
    r"康养|医养|养生|医药|药业|生物|食品|农业|旅游|酒店|餐饮|人力资源|城市建设|城建|城投|交投|水务|燃气|热力|通信|"
    r"新材料|新能源|汽车|光电|化工|钢铁|矿业|港口|航运|安防|检测|测绘|规划|运营|商业|产业|供应|租赁|金融|保险|证券|"
    r"信息|系统|集成|自动化|电器|仪器|仪表|设备|器材|家具|纺织|服饰|印刷|包装|广告|会展|传播|体育|健身)$"
)


def company_core(name: str) -> str:
    """公司全称 → 字号（2~4 个汉字）；推不出可靠字号时返回空串。"""
    s = (name or "").strip()
    for _ in range(3):
        s2 = _RE_REGION_PREFIX.sub("", s)
        if s2 == s:
            break
        s = s2
    prev = None
    while prev != s:
        prev = s
        s = _RE_INDUSTRY_SUFFIX.sub("", _RE_COMPANY_SUFFIX.sub("", s))
    if not re.fullmatch(r"[一-鿿]{2,4}", s) or s in _NAME_STOP_WORDS:
        return ""
    return s


def derive_project_stems(findings: "Findings", texts) -> int:
    """
    项目名称常常省掉结尾的「项目 / 工程」出现（如「XX未来社区综合体构造柱」），
    已识别的「XX未来社区综合体项目」去掉结尾后，若在文中确实单独出现过，也一并加入。返回新增条数。
    """
    fulls = sorted((it.term for it in findings.items.values() if it.cat == "project"), key=len, reverse=True)
    if not fulls:
        return 0
    strip_full = re.compile("|".join(re.escape(n) for n in fulls))
    cleaned = [strip_full.sub("〇", t) for t in texts]
    added = 0
    for full in fulls:
        stem = re.sub(r"(?:项目|工程)$", "", full)
        if stem == full or len(stem) < 6 or not project_specific(stem) or stem in findings.items:
            continue
        hits = [t for t in cleaned if stem in t]
        if not hits:
            continue
        for i, t in enumerate(hits[:3]):
            findings.add(stem, "project", f"项目名称（「{full}」省略结尾）", next(iter(findings.items[full].files), ""), sample=t)
        findings.items[stem].count = sum(t.count(stem) for t in hits)
        findings.items[stem].files = set(findings.items[full].files)
        added += 1
    return added


def derive_short_names(findings: "Findings", texts) -> int:
    """
    根据已识别的公司全称推断字号，并在全文里确认它确实被单独使用过
    （如「云帆112」「20250311云帆 …」「（云帆001～035号）」），再作为企业简称加入。返回新增条数。
    """
    full_names = sorted((it.term for it in findings.items.values() if it.cat == "company"), key=len, reverse=True)
    if not full_names:
        return 0
    strip_full = re.compile("|".join(re.escape(n) for n in full_names))
    cleaned = [strip_full.sub("〇", t) for t in texts]
    added = 0
    for full in full_names:
        core = company_core(full)
        if not core or core in findings.items:
            continue
        ctx = re.compile(
            rf"(?:(?<![一-鿿]){re.escape(core)}|{re.escape(core)}(?![一-鿿])|"
            rf"{re.escape(core)}(?=公司|集团|方|号|编号|项目|字第))"
        )
        hits = [t for t in cleaned if ctx.search(t)]
        if not hits:
            continue
        n = sum(len(ctx.findall(t)) for t in hits)
        files = set(findings.items[full].files)
        for i, t in enumerate(hits):
            findings.add(core, "company", f"企业简称（由「{full}」推断）", next(iter(files), ""), sample=t if i < 3 else "")
        findings.items[core].count = n
        findings.items[core].files = files
        added += 1
    return added


# ---------------------------------------------------------------------------
# Detector 主类
# ---------------------------------------------------------------------------

class Detector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.opts = cfg.get("options") or {}
        self.whitelist = {w.strip() for w in (cfg.get("whitelist") or []) if w.strip()}
        self.whitelist_lower = {w.lower() for w in self.whitelist}
        self.custom_rules = parse_keywords(cfg.get("keywords") or [])
        self.seen_texts: dict[str, None] = {}  # 扫描过的文本（去重、保序），用于推断企业简称

    def allowed(self, term: str) -> bool:
        t = (term or "").strip()
        if not t or len(t) < 2:
            return False
        if t in self.whitelist or t.lower() in self.whitelist_lower:
            return False
        # 避免把已经脱敏的占位符重复识别
        if re.fullmatch(r"\[[\u4e00-\u9fffA-Za-z]+_\d{2,4}\]", t):
            return False
        if re.fullmatch(r"\*+", t):
            return False
        return True

    def _opt(self, key: str) -> bool:
        return bool(self.opts.get(key, True))

    def detect_text(self, text: str, in_code: bool = False) -> list[tuple[str, str, str, str]]:
        """
        识别一段文本中的敏感信息。
        返回列表: [(term, cat, rule, custom_replace), ...]
        """
        if not text or not isinstance(text, str):
            return []
        if in_code and not self._opt("scan_code_blocks"):
            return []

        results: list[tuple[str, str, str, str]] = []
        seen_local = set()
        if len(self.seen_texts) < 200000:
            self.seen_texts[text] = None

        def emit(term: str, cat: str, rule: str, custom_rep: str = ""):
            term = (term or "").strip()
            if not self.allowed(term):
                return
            key = (term, cat)
            if key not in seen_local:
                seen_local.add(key)
                results.append((term, cat, rule, custom_rep))

        # 1. 自定义敏感词 / 正则（优先级最高）
        for cr in self.custom_rules:
            for m in cr.regex.finditer(text):
                val = m.group(1) if m.lastindex else m.group(0)
                emit(val, "keyword", "自定义规则", cr.replace)

        # 2. 技术凭证与密钥
        if self._opt("detect_api_key"):
            for m in _RE_PEM.finditer(text):
                emit(m.group(0), "api_key", "PEM私钥")
            for m in _RE_JWT.finditer(text):
                emit(m.group(1), "api_key", "JWT令牌")
            for m in _RE_KNOWN_KEY.finditer(text):
                emit(m.group(1), "api_key", "API密钥")
            for m in _RE_KV_SECRET.finditer(text):
                val = m.group(2).strip()
                if len(val) >= 6 and not val.startswith("[") and "*" not in val[:3]:
                    emit(val, "api_key", "键值凭证")

        if self._opt("detect_conn_str"):
            for m in _RE_CONN_STR.finditer(text):
                emit(m.group(1), "conn_str", "数据库连接串")

        if self._opt("detect_internal_url"):
            for m in _RE_INTERNAL_URL.finditer(text):
                emit(m.group(0), "internal_url", "内网地址")
            for m in _RE_LOCAL_PATH.finditer(text):
                emit(m.group(0), "internal_url", "本机路径")

        if self._opt("detect_ip"):
            for m in _RE_IPV4.finditer(text):
                ip = m.group(1)
                prefix = text[max(0, m.start(1) - 18) : m.start(1)]
                suffix = text[m.end(1) : m.end(1) + 8]
                if ipv4_ok(ip, prefix, suffix):
                    emit(ip, "ip", "IPv4地址")
            for m in _RE_IPV6.finditer(text):
                cand = m.group(1)
                try:
                    ipaddress.IPv6Address(cand)
                    emit(cand, "ip", "IPv6地址")
                except ValueError:
                    pass

        # 3. 强格式 PII 与企业编码（即使在代码块中也值得检出邮箱/身份证/统一信用代码/手机）
        if self._opt("detect_email"):
            for m in _RE_EMAIL.finditer(text):
                emit(m.group(1), "email", "邮箱正则")

        if self._opt("detect_idcard"):
            for m in _RE_IDCARD.finditer(text):
                if idcard_ok(m.group(1)):
                    emit(m.group(1), "idcard", "身份证校验位")

        if self._opt("detect_uscc"):
            for m in _RE_USCC.finditer(text):
                if uscc_ok(m.group(1)):
                    emit(m.group(1), "uscc", "信用代码校验")

        if self._opt("detect_phone"):
            for m in _RE_MOBILE.finditer(text):
                emit(m.group(1), "phone", "手机号正则")
            for m in _RE_LANDLINE.finditer(text):
                # 排除日期如 2026-11-19
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(1)):
                    emit(m.group(1), "phone", "座机正则")

        if self._opt("detect_passport"):
            for m in _RE_PASSPORT.finditer(text):
                emit(m.group(1), "passport", "护照标签")

        if self._opt("detect_bankcard") or self._opt("detect_bank_account"):
            for m in _RE_BANK_DIGITS.finditer(text):
                raw = m.group(1)
                digits = re.sub(r"\D", "", raw)
                prefix = text[max(0, m.start(1) - 18) : m.start(1)]
                if self._opt("detect_bankcard") and luhn_ok(digits):
                    emit(raw, "bankcard", "Luhn银行卡校验")
                elif self._opt("detect_bank_account") and re.search(r"账号|账户|银行|卡号|对公|收款|汇款", prefix):
                    emit(raw, "bank_account", "账号上下文")

        if in_code:
            # 代码块内不做中文人名、通用公司、金额等模糊匹配，避免误伤代码标识符
            return results

        # 4. 企业名称与地址
        if self._opt("detect_company"):
            for m in _RE_CN_COMPANY.finditer(text):
                comp = _clean_cn_company(m.group(1))
                if comp:
                    emit(comp, "company", "企业名称后缀")
            for m in _RE_EN_COMPANY.finditer(text):
                emit(m.group(1).strip(), "company", "英文企业后缀")

        # 「XXX（以下简称YYY）」定义的项目 / 单位名称及其简称
        for m in _RE_ALIAS_DEF.finditer(text):
            name = _clean_name_prefix(m.group(1).strip())
            alias = m.group(2).strip()
            if len(name) < 4:
                continue
            if _RE_COMPANY_END.search(name) and self._opt("detect_company"):
                comp = _clean_cn_company(name)
                if not comp:
                    continue
                emit(comp, "company", "名称定义（以下简称）")
                cat = "company"
            elif _RE_PROJECT_END.search(name) and project_specific(name) and self._opt("detect_project"):
                emit(name, "project", "名称定义（以下简称）")
                cat = "project"
            else:
                continue
            if (len(alias) >= 2 and alias not in _ALIAS_GENERIC and alias != name
                    and not re.match(r"[本该我贵此其]", alias) and not re.fullmatch(r"[\d\W_]+", alias)):
                emit(alias, cat, "名称定义的简称")

        if self._opt("detect_address"):
            for m in _RE_ADDRESS.finditer(text):
                addr = _ADDR_PREFIX_NOISE.sub("", m.group(1).strip()).strip()
                if len(addr) >= 6:
                    emit(addr, "address", "详细地址")

        amount_terms = set()
        if self._opt("detect_amount"):
            for m in _RE_AMOUNT_CURRENCY.finditer(text):
                amt = m.group(0).strip()
                amount_terms.add(amt)
                emit(amt, "amount", "币种金额")
            for m in _RE_AMOUNT_YUAN.finditer(text):
                amt = m.group(1)
                if not any(amt in at for at in amount_terms):
                    amount_terms.add(amt)
                    emit(amt, "amount", "金额（元）")

        # 5. 行内标签提取（如 联系人：张伟  项目名称：云栖系统升级）
        for lbl_pat, cat, rule_name in _INLINE_LABELS:
            opt_map = {
                "person": "detect_person",
                "company": "detect_company",
                "project": "detect_project",
                "bank_account": "detect_bank_account",
                "address": "detect_address",
                "amount": "detect_amount",
            }
            if not self._opt(opt_map[cat]):
                continue
            pat = re.compile(
                rf"(?<![\u4e00-\u9fffA-Za-z])(?:[\u4e00-\u9fff]{{0,4}})?{lbl_pat}\s*[:：]\s*([^{_INLINE_STOP_CHARS}]{{2,60}})"
            )
            for m in pat.finditer(text):
                val = m.group(1).strip().strip("\"'“”‘’()（）")
                if not val or val in _NAME_STOP_WORDS:
                    continue
                if cat == "person":
                    cand = re.split(r"[,，]|\s{2,}|\s+(?=\d|[A-Za-z0-9._%+-]+@|手机|电话|邮箱|身份证|部门|职务|Email)", val)[0].strip()
                    if name_like(cand):
                        emit(cand, "person", rule_name)
                elif cat == "company":
                    cand = re.split(r"[,，]|\s{2,}", val)[0].strip()
                    comp = _clean_cn_company(cand) if re.search(r"(?:公司|集团|院|所)$", cand) else cand
                    if comp and len(comp) >= 3 and not any(x in comp for x in ("待定", "无", "如下")):
                        emit(comp, "company", rule_name)
                elif cat == "project":
                    cand = re.split(r"[,，]|\s{2,}", val)[0].strip()
                    if len(cand) >= 3 and cand not in _NAME_STOP_WORDS:
                        emit(cand, "project", rule_name)
                elif cat == "bank_account":
                    digits = re.sub(r"\D", "", val)
                    if 10 <= len(digits) <= 25:
                        num = re.match(r"[\d -]{10,30}", val)
                        if num:
                            emit(num.group(0).strip(), "bank_account", rule_name)
                elif cat == "address":
                    cand = re.split(r"[,，]|\s{2,}|(?:邮编|电话|联系人)", val)[0].strip()
                    if len(cand) >= 6:
                        emit(cand, "address", rule_name)
                elif cat == "amount":
                    cand = re.split(r"\s{2,}", val)[0].strip()
                    if any(cand in at for at in amount_terms):
                        continue
                    if re.search(r"\d|[壹贰叁肆伍陆柒捌玖拾佰仟万亿]", cand):
                        emit(cand, "amount", rule_name)

        return results

    def detect_kv_cell(self, label: str, cell_text: str) -> list[tuple[str, str, str, str]]:
        """
        键值对表格（| 联系人 | 张伟 |）：用左侧单元格当标签。
        左侧必须像标签（短、不含数字），本格不能本身就是标签（如表头「合同金额（元）」）。
        """
        lab = (label or "").strip()
        val = (cell_text or "").strip()
        if not lab or not val or len(lab) > 16 or re.search(r"\d", lab):
            return []
        if classify_header(val) is not None and not re.search(r"\d", val):
            return []
        return self.detect_table_cell(lab, val)

    def detect_cover_lines(self, lines) -> list[tuple[str, str, str, str]]:
        """
        文档开头几行（封面 / 标题）里的项目名称，例如：
          「杭州XX未来社区综合体项目」「XX大厦工程竣工结算审核报告」
        """
        if not self._opt("detect_project"):
            return []
        out = []
        seen = set()
        for raw in lines:
            t = re.sub(r"^#+\s*", "", (raw or "").strip())
            if not 6 <= len(t) <= 60 or re.search(r"[，。；！？：:,;!?]", t) or _RE_HEADING_ENUM.match(t):
                continue
            m = re.fullmatch(r"(.{4,40}?(?:项目|工程))(?:\s*[（(][^）)]{1,12}[）)])?", t)
            if not m:
                m = re.match(r"(.{4,40}?(?:项目|工程))" + _RE_TITLE_TAIL.pattern, t)
            if not m:
                continue
            name = m.group(1).strip()
            if len(name) >= 8 and project_specific(name) and self.allowed(name) and name not in seen:
                seen.add(name)
                out.append((name, "project", "封面标题", ""))
        return out

    def detect_table_cell(self, header: str, cell_text: str) -> list[tuple[str, str, str, str]]:
        """
        结合表头或相邻标签列，对单元格内容做上下文增强识别。
        """
        val = (cell_text or "").strip()
        if not val:
            return []

        # 先运行通用检测
        found = self.detect_text(val)

        cat = classify_header(header)
        if not cat:
            return found

        opt_map = {
            "person": "detect_person",
            "phone": "detect_phone",
            "email": "detect_email",
            "idcard": "detect_idcard",
            "passport": "detect_passport",
            "bankcard": "detect_bankcard",
            "bank_account": "detect_bank_account",
            "company": "detect_company",
            "uscc": "detect_uscc",
            "address": "detect_address",
            "project": "detect_project",
            "amount": "detect_amount",
            "api_key": "detect_api_key",
            "ip": "detect_ip",
        }
        if cat in opt_map and not self._opt(opt_map[cat]):
            return found

        existing_terms = {t for t, _, _, _ in found}
        if val in existing_terms or not self.allowed(val):
            return found

        # 单值单元格按列头上下文精准补充
        if len(val) <= 80 and "\n" not in val:
            if cat in ("company", "project", "address", "person") and not re.search(r"[\u4e00-\u9fffA-Za-z]", val):
                return found  # 纯数字不可能是名称（如「桩基工程完成」右边的进度款）
            if cat == "project" and not project_specific(val):
                return found  # 「土建总包工程」这类通用专业名称不算项目名
            if cat == "person" and name_like(val):
                found.append((val, "person", f"表格列「{header.strip()}」", ""))
            elif cat == "company" and len(val) >= 3 and val not in _NAME_STOP_WORDS:
                found.append((val, "company", f"表格列「{header.strip()}」", ""))
            elif cat == "project" and len(val) >= 3 and val not in _NAME_STOP_WORDS:
                found.append((val, "project", f"表格列「{header.strip()}」", ""))
            elif cat == "address" and len(val) >= 5 and val not in _NAME_STOP_WORDS:
                found.append((val, "address", f"表格列「{header.strip()}」", ""))
            elif cat == "bank_account" and 10 <= len(re.sub(r"\D", "", val)) <= 25:
                found.append((val, "bank_account", f"表格列「{header.strip()}」", ""))
            elif cat == "amount" and re.search(r"\d|[壹贰叁肆伍陆柒捌玖拾佰仟万亿]", val):
                found.append((val, "amount", f"表格列「{header.strip()}」", ""))
            elif cat == "api_key" and len(val) >= 6 and val not in _NAME_STOP_WORDS:
                found.append((val, "api_key", f"表格列「{header.strip()}」", ""))
            elif cat == "passport" and re.fullmatch(r"[A-Za-z0-9]{6,14}", val):
                found.append((val, "passport", f"表格列「{header.strip()}」", ""))
            elif cat == "phone" and 7 <= len(re.sub(r"\D", "", val)) <= 16:
                found.append((val, "phone", f"表格列「{header.strip()}」", ""))

        return found
