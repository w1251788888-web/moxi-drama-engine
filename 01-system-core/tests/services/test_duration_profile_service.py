from app.services.duration_profile_service import (
    DurationProfile,
    duration_profile_from_seconds,
    infer_duration_profile,
)


def test_ninety_seconds_is_the_manga_baseline():
    profile = duration_profile_from_seconds(90)

    assert profile.duration_seconds == 90
    assert profile.target_chars == 1200
    assert profile.min_chars == 1000
    assert profile.max_chars == 1550
    assert profile.count_mode == "pure_chars"


def test_custom_duration_scales_from_ninety_second_baseline():
    profile = duration_profile_from_seconds(120)

    assert profile.duration_seconds == 120
    assert profile.target_chars == 1600
    assert profile.min_chars == 1330
    assert profile.max_chars == 2070


def test_explicit_target_defaults_to_ten_percent_window():
    profile = infer_duration_profile(
        duration_seconds=90,
        explicit_target=2000,
        market_format="用户自定义 2000 字短剧",
    )

    assert profile.target_chars == 2000
    assert profile.min_chars == 1800
    assert profile.max_chars == 2200


def test_infer_duration_profile_keeps_user_explicit_bounds():
    profile = infer_duration_profile(
        duration_seconds=180,
        explicit_min=2200,
        explicit_max=2600,
        explicit_target=2400,
        market_format="三分钟开篇漫剧",
    )

    assert profile == DurationProfile(
        duration_seconds=180,
        target_chars=2400,
        min_chars=2200,
        max_chars=2600,
        count_mode="pure_chars",
        market_format="三分钟开篇漫剧",
    )
