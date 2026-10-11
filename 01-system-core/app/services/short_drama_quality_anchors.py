"""测试页"质量锚点提示块"工具（从 short_drama_writing.py 抽出）。

- infer_testing_sample_track：根据 req.sample_track / 各类文本字段，推断该项目对标的样本赛道
  返回 (track_name, track_notes)
- build_testing_quality_anchor_block：组装一段 prompt 用的锚点说明（包含赛道名 + 共性底线 + 段落硬要求）

两个函数都是"纯计算"：只读 TestingScriptRequest 字段，不查 DB、不调 AI、没有 IO。
搬到 services 后，未来 generate / validate / deep-audit / auto-fix 等多个 endpoint
进子文件就不必再"伸手回主 router 拿"。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def infer_testing_sample_track(req: "TestingScriptRequest") -> tuple[str, list[str]]:
    """根据请求字段，推断该项目对标的样本赛道。

    优先级：
    1. req.sample_track 显式指定 4 个 sample_track_* → 直接返回
    2. 用 brief / worldview / 各种集级字段做关键词匹配
    3. audience_axis 作为最后一道兜底（女频 / 男频 走不同分支）
    4. 全部不命中 → 通用悬念反转型
    """
    explicit_track = str(req.sample_track or "").strip()
    if explicit_track == "sample_track_d_realistic_family":
        return (
            "D. 现实情感/乡土亲情型",
            [
                "推进重点放在关系亏欠、现实压力、代际失衡，不靠密集反转。",
                "情绪可以克制，但必须有现实后果、关系余波或没说出口的情感。",
            ],
        )
    if explicit_track == "sample_track_c_misrecognition_secret":
        return (
            "C. 错认婚配/秘密延迟兑现型",
            [
                "推进重点是错认、误会、信息差和承诺被打断，不要急着把真相一次说透。",
                "甜点和温柔必须建立在风险未解除之上。",
            ],
        )
    if explicit_track == "sample_track_b_power_taming":
        return (
            "B. 权力驯服/危险关系型",
            [
                "冲突重点不在吵，而在谁压谁、谁立规矩、谁改规矩、谁服从谁。",
                "同一段最好同时完成关系温度变化和权力位置变化。",
            ],
        )
    if explicit_track == "sample_track_a_high_pressure_female":
        return (
            "A. 高压情感打脸型",
            [
                "推进重点是伤害被看见、证据反制、公开站队、关系翻面和权力易手。",
                "爽点优先写成公开反击，而不是嘴上骂赢。",
            ],
        )

    text = " ".join(
        str(item or "").strip()
        for item in [
            req.project_type,
            req.audience_axis,
            req.genre_main,
            req.genre_sub,
            req.subgenre_track,
            req.sample_track,
            req.brief,
            req.worldview,
            req.conflict,
            req.episode_title,
            req.episode_summary,
            req.episode_conflict,
            req.episode_hook,
            req.continuity_notes,
        ]
    )

    if any(token in text for token in ["回乡", "返乡", "乡", "上坟", "送站", "送别", "罚单", "债务", "看病", "父亲", "母亲", "奶奶"]):
        return (
            "D. 现实情感/乡土亲情型",
            [
                "推进重点放在关系亏欠、现实压力、代际失衡，不靠密集反转。",
                "情绪可以克制，但必须有现实后果、关系余波或没说出口的情感。",
            ],
        )

    if any(token in text for token in ["替嫁", "错认", "误认", "错嫁", "新婚", "花轿", "盖头", "婚配", "秘密", "身份错位"]):
        return (
            "C. 错认婚配/秘密延迟兑现型",
            [
                "推进重点是错认、误会、信息差和承诺被打断，不要急着把真相一次说透。",
                "甜点和温柔必须建立在风险未解除之上。",
            ],
        )

    if any(token in text for token in ["督军", "少帅", "军阀", "规矩", "家法", "权势", "驯服", "压服", "危险关系"]):
        return (
            "B. 权力驯服/危险关系型",
            [
                "冲突重点不在吵，而在谁压谁、谁立规矩、谁改规矩、谁服从谁。",
                "同一段最好同时完成关系温度变化和权力位置变化。",
            ],
        )

    if "女频" in str(req.audience_axis or "") or any(token in text for token in ["豪门", "打脸", "偏爱", "背叛", "录音", "证据", "站队", "虐渣"]):
        return (
            "A. 高压情感打脸型",
            [
                "推进重点是伤害被看见、证据反制、公开站队、关系翻面和权力易手。",
                "爽点优先写成公开反击，而不是嘴上骂赢。",
            ],
        )

    if "男频" in str(req.audience_axis or ""):
        return (
            "通用逆袭/规则兑现型",
            [
                "推进重点是压制开场、规则触发、主动回击、围观见证和局势翻转。",
                "结果必须可见，不能只有设定和情绪。",
            ],
        )

    return (
        "通用悬念反转型",
        [
            "推进重点是关系、信息、权力至少动一层，不能只换地点继续说同样的话。",
            "每段都要把动作、后果和追问绑在一起。",
        ],
    )


def build_testing_quality_anchor_block(req: "TestingScriptRequest") -> str:
    """组装一段给 LLM 用的"质量锚点"提示块（赛道+共性底线+段落硬要求）。"""
    track_name, track_notes = infer_testing_sample_track(req)

    segment_notes: dict[str, list[str]] = {
        "hook": [
            "本段前3行内必须出现可见异常、威胁、代价、关系裂口或身份压制。",
            "若不是第1集，本段前5行必须接住上一集最后3行的动作/物件/站位，不能用清晨、第二天、已经热闹概括跳过爆点。",
            "开场最好直接让观众产生一个具体问题，不要中性起步。",
            "hook 不能只停在摆开阵势，结尾前必须出现一次主角反刺、围观升级或新的公开压迫。",
        ],
        "validation": [
            "本段必须通过试探、逼问、误判、露证据、压制或新阻碍，让关系/信息/权力至少一项前进。",
            "每2-3句对白就要出现一次卡点，不能一直平铺解释。",
        ],
        "explosion": [
            "本段必须把前面埋的冲突兑现成动作后果，最好出现第三方见证、站队变化或权力翻转。",
            "能亮证据就别只暗示，能公开翻盘就别只停在心里痛快。",
        ],
        "resolution": [
            "本段结尾必须挂住未完成承诺，不是降温总结。",
            "结尾停在具体动作、台词或新发现上，让下一拍有明确承接对象。",
        ],
        "scene": [
            "当前是整场测试，必须同时写出目的、阻碍、动作、结果和尾巴。",
            "整集按“承接上集压力→加码→爆发/损失落地→具体物件拉钩”执行，不能把爆点延到下一集。",
            "现实题材OS最多1-2处，首尾不用OS，禁用仿佛/似乎/眼神中/气氛等小说化句子。",
            "整场至少推进关系/信息/权力中的一项，最好两项叠加。",
        ],
    }

    key = (req.segment_id or "scene") if req.mode == "segment" else "scene"
    lines = [
        f"- 当前对标模型：{track_name}",
        "- 只学习推进器和质感，不照搬样板剧本的人名、桥段和设定。",
        "- 共性底线：本段至少推进关系变化、信息差变化、权力变化中的一项，最好两项叠加。",
        "- 共性底线：动作必须可拍，后果必须可见，重要结果尽量让第三方看见。",
    ]
    lines.extend(f"- {note}" for note in track_notes)
    lines.extend(f"- {note}" for note in segment_notes.get(key, []))

    if req.mode != "segment" and req.scene_no == 1 and not str(req.current_content or "").strip():
        lines.extend([
            "- 当前是本集第一场，优先兑现本集摘要里最强的公开压迫、羞辱、异常或代价，不要先跳到后置解释场。",
            "- 第一场开局 8-12 行内必须让观众看见主角正在失去什么，或者反派正在怎样压他。",
        ])

    if track_name.startswith("A.") and key == "hook":
        lines.append("- 打脸女频的 hook 不能只说“我有证据”，关键把柄内容至少半露一句，并尽快引出围观反应或站位变化。")
    if track_name.startswith("B.") and key == "explosion":
        lines.append("- 危险关系的 explosion 不能只爆情绪，要明确写出谁改了规矩、谁失了面子、谁暂时占上风。")
    if track_name.startswith("C.") and key == "resolution":
        lines.append("- 错认秘密型的 resolution 要把温柔停在危险上：关系刚靠近，就被新发现或追兵打断。")
    if track_name.startswith("D.") and key == "scene":
        lines.append("- 现实情感整场要把现实细节写成戏：车费、罚单、医院、债务、咳血、送站这类后果要能落地。")

    return "\n".join(lines)
