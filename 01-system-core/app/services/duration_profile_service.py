"""Episode duration to pure-character budget helpers.

The project baseline is 90 seconds ~= 1200 pure Chinese characters. Current
research uses an elastic 1000-1550 delivery window for 90 seconds: the lower
bound prevents thin drafts, while the upper bound leaves room for watchable
scene movement instead of forcing a brittle narrow interval.
"""

from __future__ import annotations

from dataclasses import dataclass


BASELINE_SECONDS = 90
BASELINE_TARGET_CHARS = 1200
BASELINE_MIN_CHARS = 1000
BASELINE_MAX_CHARS = 1550
DEFAULT_TOLERANCE_RATIO = 0.10
MIN_TOLERANCE_CHARS = 50


@dataclass(frozen=True)
class DurationProfile:
    duration_seconds: int
    target_chars: int
    min_chars: int
    max_chars: int
    count_mode: str = "pure_chars"
    market_format: str = ""


def _round_to_ten(value: float) -> int:
    return int(round(value / 10.0) * 10)


def _default_tolerance(target_chars: int) -> int:
    return max(MIN_TOLERANCE_CHARS, _round_to_ten(target_chars * DEFAULT_TOLERANCE_RATIO))


def duration_profile_from_seconds(
    duration_seconds: float | int,
    *,
    market_format: str = "",
) -> DurationProfile:
    seconds = max(1, int(round(float(duration_seconds or BASELINE_SECONDS))))
    ratio = seconds / BASELINE_SECONDS
    target = _round_to_ten(BASELINE_TARGET_CHARS * ratio)
    return DurationProfile(
        duration_seconds=seconds,
        target_chars=target,
        min_chars=max(0, _round_to_ten(BASELINE_MIN_CHARS * ratio)),
        max_chars=max(0, _round_to_ten(BASELINE_MAX_CHARS * ratio)),
        market_format=market_format,
    )


def infer_duration_profile(
    *,
    duration_seconds: float | int | None = None,
    episode_minutes: float | int | None = None,
    explicit_min: int | None = None,
    explicit_max: int | None = None,
    explicit_target: int | None = None,
    market_format: str = "",
) -> DurationProfile:
    seconds = duration_seconds
    if seconds is None:
        seconds = float(episode_minutes or 1.5) * 60

    inferred = duration_profile_from_seconds(seconds, market_format=market_format)
    target = int(explicit_target or inferred.target_chars)
    if explicit_target is not None and explicit_min is None and explicit_max is None:
        tolerance = _default_tolerance(target)
        min_chars = max(0, target - tolerance)
        max_chars = target + tolerance
    else:
        min_chars = int(explicit_min if explicit_min is not None else inferred.min_chars)
        max_chars = int(explicit_max if explicit_max is not None else inferred.max_chars)

    if min_chars > max_chars:
        min_chars, max_chars = max_chars, min_chars
    if not target:
        target = int(round((min_chars + max_chars) / 2))
    return DurationProfile(
        duration_seconds=inferred.duration_seconds,
        target_chars=target,
        min_chars=min_chars,
        max_chars=max_chars,
        market_format=market_format,
    )
