"""H10 评分后校正（基于 82 集人评配对的线性系数）

调用方式：
    from app.services.scoring_calibration import apply_calibration
    calibrated = apply_calibration(quality_report)

输入字段：reviewer 输出的 quality_report dict（含 hook/density/emotion/benchmark_total/...）
输出字段：同 dict + `calibrated_*`（不覆盖原始模型分，便于审计）

系数源：data/benchmark/human_scoring/calibration_coefficients.json
策略：均值校正（mean_bias）+ 线性映射（linear_a/b）二选一，默认 mean_bias（更稳）。
低相关性维度（r < 0.2）只做均值校正，不做线性映射，避免"低相关线性外推"导致的二次偏差。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_COEF_PATH = Path(__file__).resolve().parents[2] / "data" / "benchmark" / "human_scoring" / "calibration_coefficients.json"

# 字段映射：模型输出 key → 校正后写入 key
_DIM_FIELDS = (
    "hook",
    "density",
    "emotion",
    "benchmark_total",
    "char_consist",
    "seed_payoff",
    "fact_consist",
    "continuity_total",
)

_LOW_R_THRESHOLD = 0.2  # 相关性 < 0.2 的维度退化为均值校正


def _load_coef() -> dict[str, dict]:
    if not _COEF_PATH.exists():
        return {}
    try:
        return json.loads(_COEF_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


_COEF = _load_coef()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _bounds_for(field: str) -> tuple[float, float]:
    if field == "hook" or field == "char_consist":
        return 0.0, 40.0
    if field in ("density", "emotion", "seed_payoff", "fact_consist"):
        return 0.0, 30.0
    if field in ("benchmark_total", "continuity_total"):
        return 0.0, 100.0
    return 0.0, 100.0


def calibrate_value(field: str, value: float, mode: str = "mean") -> float:
    """对单维度分数做校正。

    mode='mean': 减去 mean_bias（默认，最稳）
    mode='linear': 应用 a*x + b（仅对 r >= 0.2 的维度有效，否则退化 mean）
    """
    coef = _COEF.get(field)
    if not coef:
        return value
    lo, hi = _bounds_for(field)
    if mode == "linear" and abs(coef.get("correlation_r", 0.0)) >= _LOW_R_THRESHOLD:
        a = coef.get("linear_a", 1.0)
        b = coef.get("linear_b", 0.0)
        return _clamp(a * value + b, lo, hi)
    bias = coef.get("mean_bias", 0.0)
    return _clamp(value - bias, lo, hi)


def apply_calibration(report: dict[str, Any], mode: str = "mean", inline: bool = False) -> dict[str, Any]:
    """对一份 quality_report 应用校准。

    inline=False: 在 dict 中追加 calibrated_<field> 字段（保留原始）
    inline=True: 直接覆盖原字段
    """
    if not _COEF:
        return report
    out = dict(report)
    for field in _DIM_FIELDS:
        if field not in report:
            continue
        try:
            raw = float(report[field])
        except Exception:
            continue
        new = round(calibrate_value(field, raw, mode=mode), 1)
        if inline:
            out[field] = new
        else:
            out[f"calibrated_{field}"] = new
    return out


def calibration_summary() -> dict[str, Any]:
    """返回当前校准系数摘要（给监控/调试用）"""
    return {
        "coefficients_loaded": bool(_COEF),
        "fields": list(_COEF.keys()),
        "samples_per_field": {k: v.get("samples") for k, v in _COEF.items()},
        "biases": {k: v.get("mean_bias") for k, v in _COEF.items()},
    }
