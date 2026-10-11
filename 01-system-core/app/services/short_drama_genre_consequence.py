"""题材原生后果识别。

这个模块只做一件事：把"通用可拍后果"和"具体题材里的原生后果"分开。
避免所有题材都被订单、投诉、封条、检测这套商业现实词表误判。
"""
from __future__ import annotations

from typing import Any


COMMERCIAL_PUBLIC_TOKENS: tuple[str, ...] = (
    "当场", "门口", "围观", "街坊", "顾客", "记者", "直播", "评论区", "热榜", "封条",
    "停业", "退款", "订单", "排队", "罚款", "处罚", "签收", "回执", "名单", "备案",
    "站队", "录下", "看见", "手机镜头", "镜头", "拍下", "拍着", "举起手机",
)

COMMERCIAL_CONSEQUENCE_TOKENS: tuple[str, ...] = (
    "投诉", "封条", "罚单", "律师函", "合同", "断供", "降价", "退款", "订单取消", "房东",
    "涨租", "供应商", "检测", "回执", "封存", "处罚", "停业", "查封", "备案", "热榜",
    "评论区", "排队散", "顾客退", "摊车", "订单", "押金", "批号", "原料",
)

ARCHIVE_CONTEXT_TOKENS: tuple[str, ...] = (
    "悬疑档案", "档案", "越界", "门禁", "审批号", "权限", "工号栏", "主控台", "何正声",
    "何父", "家族信托", "转出程序", "锁舌", "报告送达", "查阅中", "S-01", "B-7",
)

ARCHIVE_PUBLIC_TOKENS: tuple[str, ...] = (
    "越界报告", "报告已送达", "报告送达", "送达何正声", "何正声", "何父", "查阅中",
    "主控台", "黑色审批号", "审批号", "系统弹出", "广播", "安保", "门禁", "倒计时",
    "通讯接入", "家族信托",
)

ARCHIVE_CONSEQUENCE_TOKENS: tuple[str, ...] = (
    "门禁锁死", "锁死", "锁舌", "转出程序", "工号栏", "黑屏", "权限黑屏", "权限降级",
    "报告进度条", "100%", "审批号刷新", "倒计时", "通讯接入", "安保交接", "报告已送达",
    "查阅中", "越界报告", "主控台弹出",
)

GENERIC_EVIDENCE_CONSEQUENCE_TOKENS: tuple[str, ...] = (
    "证据", "把柄", "监控", "截图", "录音", "纸角", "纸页", "文件", "抽走", "扯出",
    "抢走", "出生证明", "亲子鉴定", "证件", "名单",
)


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{key}:{_as_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_as_text(item) for item in value)
    return str(value or "")


def _hits(text: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for token in tokens if token and token in text)


def infer_consequence_domain(content_text: str, *, context_text: str = "", contract: dict[str, Any] | None = None) -> str:
    full_text = "\n".join([str(context_text or ""), _as_text(contract or {}), str(content_text or "")])
    if _hits(full_text, ARCHIVE_CONTEXT_TOKENS):
        return "archive_suspense"
    if _hits(full_text, ("早餐", "馒头", "摊", "订单", "配方", "连锁", "生意", "顾客", "供应商")):
        return "commercial_realistic"
    return "generic"


def assess_consequence_gate(
    content_text: str,
    *,
    context_text: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回本题材下是否具备公开压力和可拍后果。"""
    text = str(content_text or "")
    domain = infer_consequence_domain(text, context_text=context_text, contract=contract)

    if domain == "archive_suspense":
        public_tokens = (*ARCHIVE_PUBLIC_TOKENS, *COMMERCIAL_PUBLIC_TOKENS)
        consequence_tokens = (*ARCHIVE_CONSEQUENCE_TOKENS, *GENERIC_EVIDENCE_CONSEQUENCE_TOKENS)
    elif domain == "commercial_realistic":
        public_tokens = COMMERCIAL_PUBLIC_TOKENS
        consequence_tokens = (*COMMERCIAL_CONSEQUENCE_TOKENS, *GENERIC_EVIDENCE_CONSEQUENCE_TOKENS)
    else:
        public_tokens = COMMERCIAL_PUBLIC_TOKENS
        consequence_tokens = (*GENERIC_EVIDENCE_CONSEQUENCE_TOKENS, *COMMERCIAL_CONSEQUENCE_TOKENS)

    public_hits = _hits(text, public_tokens)
    consequence_hits = _hits(text, consequence_tokens)
    return {
        "domain": domain,
        "has_public_pressure": bool(public_hits),
        "has_consequence": bool(consequence_hits),
        "public_hits": public_hits,
        "consequence_hits": consequence_hits,
    }
