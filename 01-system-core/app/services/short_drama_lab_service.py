"""
短剧市场对标实验服务
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

from app.services.story_bible_service import build_story_bible
from app.services.text_generation_v2 import generate_json, generate_text

# 外部工具 Skill（可选）。延迟加载，避免服务导入时触发 jieba/pkg_resources 警告。
CNSENTI_AVAILABLE = False


@lru_cache(maxsize=1)
def _load_cnsenti_tools():
    try:
        from skills.cnsenti_skill.cnsenti_cli import analyze_emotion_curve, check_emotion_pattern
        return analyze_emotion_curve, check_emotion_pattern
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        return None


NOVELQUICKAPP_PLATFORM_TAXONOMY = {
    "platform_name": "红果短剧",
    "source_key": "novelquickapp",
    "source_url": "https://novelquickapp.com/category",
    "content_types": ["短剧", "漫画"],
    "hot_signal": {
        "dimension": "推荐",
        "priority": ["最热", "最新", "全部"],
        "primary_learning_target": "最热",
    },
    "dimensions": {
        "背景": ["现代", "都市", "古代", "乡村", "年代", "架空", "职场", "民国", "宫廷", "校园", "荒岛"],
        "主题": ["现言", "女性成长", "脑洞", "奇幻", "玄幻", "古言", "战神", "宫斗", "仙侠", "权谋", "年代爱情", "种田", "悬疑", "喜剧", "民国爱情", "志怪", "青春", "灵异", "法律", "家国情怀", "刑侦", "抗战", "民国传奇", "武侠", "求生", "科幻", "动作", "恐怖", "商战"],
        "设定": ["打脸虐渣", "大女主", "大男主", "马甲", "重生", "穿越", "系统", "先婚后爱", "家长里短", "小人物", "神豪", "豪门", "破镜重圆", "强者回归", "虐恋", "传承觉醒", "异能", "强强联合", "赘婿逆袭", "医生", "甜宠", "娱乐圈", "青梅竹马", "神医", "追妻火葬场", "姐弟恋", "玄学", "业界精英", "一见钟情", "福宝", "反派主角", "萌宠", "捞偏门", "白月光", "双向救赎", "灵魂互换", "病娇", "方言", "暴富", "黑道", "丧尸", "特种兵"],
        "受众": ["男频", "女频"],
        "时间": ["7天内上新", "14天内上新", "30天内上新", "90天内上新"],
        "推荐": ["全部", "最新", "最热"],
    },
    "sample_titles": [
        {"title": "腹黑总裁和他的惹祸小娇妻", "tags": ["都市爱情", "追妻火葬场", "真假千金"]},
        {"title": "真孝看行动不看语言", "tags": ["家庭伦理", "极品亲戚", "马甲"]},
        {"title": "分家后我靠奶奶旧衣服赢麻了", "tags": ["女性成长", "家庭伦理", "逆袭"]},
        {"title": "绣房针魇", "tags": ["悬疑情感", "反转", "打脸虐渣"]},
        {"title": "我儿大孝，非要坑我成大帝", "tags": ["玄幻仙侠", "奇幻脑洞", "穿越"]},
        {"title": "真千金她是律界阎罗", "tags": ["女性成长", "穿越", "逆袭"]},
        {"title": "法医林砚之尸语寻踪", "tags": ["刑侦破案", "女强", "现代"]},
        {"title": "我的摸鱼搭子是上司", "tags": ["都市爱情", "马甲", "日久生情"]},
        {"title": "金媳如宝", "tags": ["都市日常", "打脸虐渣", "大男主"]},
        {"title": "清洁工大叔竟是豪门主夫", "tags": ["都市日常", "马甲", "打脸虐渣"]},
        {"title": "边境逃亡：从猪仔到地下国王", "tags": ["都市脑洞", "犯罪", "系统"]},
        {"title": "囚牢十年，只为护女一生", "tags": ["都市日常", "亲情", "打脸虐渣"]},
        {"title": "拒绝卑微讨好，反被大小姐全家宠上天", "tags": ["都市脑洞", "赘婿逆袭", "系统"]},
        {"title": "妻子的惩罚", "tags": ["女性成长", "总裁", "大女主"]},
        {"title": "迷失野人谷", "tags": ["女性成长", "冒险", "反转"]},
        {"title": "提取她们相亲愿望，我走上巅峰", "tags": ["都市脑洞", "系统", "逆袭"]},
        {"title": "别靠保姆养老", "tags": ["都市日常", "家长里短", "打脸虐渣"]},
        {"title": "母亲的三次预言", "tags": ["女性成长", "奇幻", "反转"]},
        {"title": "主母携媳，搬空侯府闯天下", "tags": ["女性成长", "打脸虐渣", "逆袭"]},
        {"title": "烧烤店谜案", "tags": ["刑侦破案", "反转", "马甲"]},
    ],
}


@dataclass(frozen=True)
class TrackBenchmark:
    big_category: str
    sub_category: str
    audience_axis: str
    script_summary: str
    ip_core: list[str]
    unit_strategy: str
    structure_rules: list[str]
    expression_rules: list[str]
    benchmark_features: list[str]
    patch_focus: list[str]
    source_platform: str = "novelquickapp"
    source_url: str = NOVELQUICKAPP_PLATFORM_TAXONOMY["source_url"]
    hot_dimensions: list[str] | None = None
    sample_titles: list[str] | None = None


TRACK_BENCHMARKS: list[TrackBenchmark] = [
    TrackBenchmark(
        big_category="女频情感",
        sub_category="追妻火葬场",
        audience_axis="female",
        script_summary="高压关系开局，女主先受伤后抽离，男主后知后觉追妻，靠误会翻面、身份代价与情绪反噬持续推进。",
        ip_core=["高位压制关系", "女主清醒抽离", "男主失控追妻"],
        unit_strategy="主线+单元混合：入局/伤害、抽离、追妻失控、真相翻面、代价兑现。",
        structure_rules=[
            "前3场必须出现明确伤害、误判或关系崩口。",
            "每个单元都要让男女主关系位置发生一次翻转。",
            "误会不能空转，必须绑定身份、利益或外部压力。",
            "集末钩子优先落在追妻受阻、真相露头、关系断裂。",
            "平台最热女频题材优先让偏爱、误会、失去与挽回在第一集就露头。",
        ],
        expression_rules=[
            "对白短、狠、带刺，避免长篇控诉。",
            "动作强调冷处理、推开、失约、拦截、追到现场。",
            "情绪释放要靠反应和局势，不靠解释。",
        ],
        benchmark_features=["强关系拉扯", "高密度误会翻面", "女主情绪价值清晰", "男主后悔成本高"],
        patch_focus=["追妻动机不足", "误会空转", "女主不够清醒", "钩子不够狠"],
        hot_dimensions=["主题:现言", "设定:追妻火葬场", "设定:豪门", "推荐:最热"],
        sample_titles=["腹黑总裁和他的惹祸小娇妻"],
    ),
    TrackBenchmark(
        big_category="女频情感",
        sub_category="替嫁先婚后爱",
        audience_axis="female",
        script_summary="女主被迫进入婚姻局，先靠身份错位与利益交换建立危机，再在试探与共患难中升温。",
        ip_core=["身份错位", "被迫婚约", "先婚后爱"],
        unit_strategy="入府/入局、试探、共患难、身份摇晃、真心确认。",
        structure_rules=[
            "开局必须把替嫁代价具体化。",
            "每单元至少一次关系试探和一次规则碰撞。",
            "甜点必须建立在风险未解除的前提上。",
            "平台女频高频设定更偏身份错位+关系拉扯，不接受无代价撒糖。",
        ],
        expression_rules=[
            "对白要兼具防备和暧昧，不直接表白。",
            "可拍动作优先：遮掩、护短、试探、拆穿。",
        ],
        benchmark_features=["设定清楚", "关系升温层次分明", "甜虐并行", "身份风险持续存在"],
        patch_focus=["替嫁设定虚", "男女主升温突兀", "风险消失过早"],
        hot_dimensions=["设定:先婚后爱", "设定:豪门", "推荐:最热"],
        sample_titles=["腹黑总裁和他的惹祸小娇妻"],
    ),
    TrackBenchmark(
        big_category="男频逆袭",
        sub_category="身份逆袭打脸",
        audience_axis="male",
        script_summary="男主在低位或伪装状态下被压制，通过身份揭露、资源翻盘和局势反杀完成连续打脸。",
        ip_core=["隐藏身份", "压制反扑", "连续打脸"],
        unit_strategy="低位压制、试探反击、小翻盘、大揭露、总清算。",
        structure_rules=[
            "开局必须让男主被低估或被羞辱。",
            "每集至少一次地位变化或认知翻面。",
            "打脸必须有见证者和明确后果。",
            "资源翻盘要看得见，不写抽象外挂。",
            "平台男频热赛道更重围观感与公开结果，不接受闷声逆袭。",
        ],
        expression_rules=[
            "对白以压制、反讽、回击为主。",
            "动作强调出手、亮牌、卡位、揭露证据。",
        ],
        benchmark_features=["爽点直接", "翻盘清晰", "压制-反扑节奏明显", "观众代偿感强"],
        patch_focus=["压制不够狠", "翻盘太快", "打脸没有围观场", "男主底牌不清"],
        hot_dimensions=["设定:大男主", "设定:打脸虐渣", "设定:强者回归", "推荐:最热"],
        sample_titles=["金媳如宝", "清洁工大叔竟是豪门主夫"],
    ),
    TrackBenchmark(
        big_category="男频逆袭",
        sub_category="校园系统装X",
        audience_axis="male",
        script_summary="低位废柴男主在校园里靠抽象装X行为制造围观，再借系统任务兑现与考试/觉醒/升学反杀完成连环逆袭，兼顾搞笑和情感推进。",
        ip_core=["低位废柴穿越", "系统任务兑现", "校园围观打脸", "嘉豪式装X名场面"],
        unit_strategy="废柴受压、抽象装X、系统奖励、围观翻盘、校花关注、升学冲刺。",
        structure_rules=[
            "前3场必须明确男主被当成笑话，并出现一次嘉豪式哗众取宠动作。",
            "系统必须在前两章内给出看得见的奖励或惩罚。",
            "每个单元都要有围观者和可视化打脸结果。",
            "第一季目标必须稳定指向进入八道口技能学院。",
            "开篇先落真实困难，再抛设定，不允许先爽后压。",
            "前三章必须体现2D漫剧快切场、强钩子、强画面感。",
            "平台分类里校园 + 系统 + 大男主属于天然热组合，必须把装X动作做成高识别名场面。",
        ],
        expression_rules=[
            "对白要中二、嘴硬、带抽象自信，但不能只剩网络段子。",
            "动作强调白板打碟、装股神、考试亮牌、觉醒翻盘、校园围观。",
            "爽点和笑点必须绑在同一个可拍动作上。",
            "系统要有傲娇毒舌人格，能和男主形成互怼节奏。",
            "文本要有网感，像热梗衍生漫剧，而不是推文改写。",
        ],
        benchmark_features=["低位逆袭强", "系统兑现快", "校园围观感足", "装X名场面高识别", "校花线有代入"],
        patch_focus=["装X梗只有标签没有场面", "系统奖励兑现太慢", "校花线工具化", "校园围观打脸不够狠", "开篇困难不够狠", "网感不足", "系统人格缺席"],
        hot_dimensions=["背景:校园", "设定:系统", "设定:大男主", "推荐:最热"],
        sample_titles=["提取她们相亲愿望，我走上巅峰"],
    ),
    TrackBenchmark(
        big_category="古风权谋",
        sub_category="替身/权臣博弈",
        audience_axis="mixed",
        script_summary="用身份秘密、朝局利益与危险关系做高压博弈，靠试探、错位、结盟与反噬推进。",
        ip_core=["危险关系", "朝局规则", "身份秘密"],
        unit_strategy="入局试探、结盟互骗、朝局升级、身份揭露、权力反噬。",
        structure_rules=[
            "每个单元至少一次规则碰撞或权力施压。",
            "关系推进必须伴随风险上升。",
            "信息差要服务权谋，不只是拖悬念。",
        ],
        expression_rules=[
            "对白克制但带刀锋，少废话。",
            "动作强调试探、借势、扣押、救场、翻供。",
        ],
        benchmark_features=["高压氛围", "权力与情感双线拉扯", "信息差可追问", "古风表达有锋利感"],
        patch_focus=["权谋像空话", "关系线弱", "信息差无兑现"],
        hot_dimensions=["背景:古代", "主题:权谋", "推荐:最热"],
        sample_titles=["主母携媳，搬空侯府闯天下"],
    ),
    TrackBenchmark(
        big_category="家庭伦理",
        sub_category="婚姻反击/亲情反噬",
        audience_axis="female",
        script_summary="围绕婚姻背叛、亲情偏置与家庭压迫展开，用现实代价和情绪反噬推动反击。",
        ip_core=["婚姻背叛", "家庭压迫", "现实反击"],
        unit_strategy="压迫、爆口、离场、反击、关系重排。",
        structure_rules=[
            "前3场必须把压迫、偏心或背叛拍实。",
            "每单元都要有现实代价，不悬空。",
            "反击必须击中家庭秩序，而不是只骂人。",
            "平台女性成长/家长里短热题更依赖现实细节，不接受漂浮空骂。",
        ],
        expression_rules=[
            "对白生活化但要有刀口。",
            "动作优先饭桌、账单、签字、离家、争夺孩子/财产等现实场景。",
        ],
        benchmark_features=["现实代入强", "情绪痛感足", "反击有效", "关系重排明显"],
        patch_focus=["生活细节假", "冲突只靠吵架", "反击不落地"],
        hot_dimensions=["主题:女性成长", "设定:家长里短", "设定:打脸虐渣", "推荐:最热"],
        sample_titles=["真孝看行动不看语言", "别靠保姆养老"],
    ),
    TrackBenchmark(
        big_category="悬疑反转",
        sub_category="秘密揭露/身份错案",
        audience_axis="mixed",
        script_summary="用秘密、失踪、错案或身份错认制造持续追问，在每个节点给出半揭露和更大的新问题。",
        ip_core=["核心秘密", "多层信息差", "连续追问"],
        unit_strategy="异常出现、误导追查、半揭露、错误答案、真相翻面。",
        structure_rules=[
            "开局必须给异常事件。",
            "每单元都要回答一个问题并抛出更大的问题。",
            "反转要回收前置信息，不能凭空掉设定。",
            "平台悬疑热题更强调单集可追问感，不能只藏信息不兑现。",
        ],
        expression_rules=[
            "对白尽量短促，少解释。",
            "动作强调发现、跟踪、质问、曝光。",
        ],
        benchmark_features=["异常开局", "信息回收", "追问链不断", "反转有因果"],
        patch_focus=["反转硬拐", "信息不回收", "悬念只拖不解"],
        hot_dimensions=["主题:悬疑", "主题:刑侦", "推荐:最热"],
        sample_titles=["烧烤店谜案", "法医林砚之尸语寻踪"],
    ),
]



PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
STEP_PROMPTS_DIR = PROMPTS_DIR / "steps"
AGENT_PROMPTS_DIR = PROMPTS_DIR / "agents"
DEFAULT_TRACK_KEY = "女频情感 / 追妻火葬场"
CUSTOM_CAMPUS_TRACK_KEY = "男频逆袭 / 校园系统装X"
DYNAMIC_CUSTOM_EPISODE_COUNT = 3
DYNAMIC_CUSTOM_EPISODE_MINUTES = 2
CUSTOM_CAMPUS_CHAPTER_TITLES = ["厕所醒魂，资格卡喉", "白板亮牌，系统催命", "校花看见，公开翻盘"]
CUSTOM_CAMPUS_REWRITE_EPISODE_START = 5
CUSTOM_CAMPUS_REWRITE_EPISODE_END = 10
CUSTOM_CAMPUS_REWRITE_MAX_ATTEMPTS = 3
CUSTOM_CAMPUS_REWRITE_TITLE_HINTS = {
    5: "试炼楼捡漏",
    6: "资格被锁",
    7: "校花连坐",
    8: "全班停赛",
    9: "封机风暴",
    10: "旧案开门",
}


def build_platform_taxonomy_report() -> dict[str, Any]:
    dimensions = NOVELQUICKAPP_PLATFORM_TAXONOMY["dimensions"]
    sample_titles = NOVELQUICKAPP_PLATFORM_TAXONOMY["sample_titles"]
    return {
        "platform_name": NOVELQUICKAPP_PLATFORM_TAXONOMY["platform_name"],
        "source_key": NOVELQUICKAPP_PLATFORM_TAXONOMY["source_key"],
        "source_url": NOVELQUICKAPP_PLATFORM_TAXONOMY["source_url"],
        "content_types": list(NOVELQUICKAPP_PLATFORM_TAXONOMY["content_types"]),
        "hot_signal": dict(NOVELQUICKAPP_PLATFORM_TAXONOMY["hot_signal"]),
        "dimensions": {key: list(value) for key, value in dimensions.items()},
        "sample_titles": [{"title": item["title"], "tags": list(item["tags"])} for item in sample_titles],
        "hot_category_summary": [
            "平台分类入口清晰，推荐 -> 最热 可直接作为赛道学习优先级。",
            "女频高频集中在女性成长、打脸虐渣、豪门、追妻火葬场、先婚后爱等组合。",
            "男频高频集中在大男主、系统、赘婿逆袭、强者回归、都市脑洞等组合。",
            "混合题材高频集中在悬疑、刑侦、奇幻脑洞、喜剧与反转。",
            "背景维度覆盖都市、现代、古代、年代、校园等，说明开场环境必须一眼可识别。",
        ],
    }


def list_track_benchmarks() -> list[dict[str, Any]]:
    return [serialize_track_benchmark(item) for item in TRACK_BENCHMARKS]


def serialize_track_benchmark(item: TrackBenchmark) -> dict[str, Any]:
    return {
        "big_category": item.big_category,
        "sub_category": item.sub_category,
        "audience_axis": item.audience_axis,
        "script_summary": item.script_summary,
        "ip_core": list(item.ip_core),
        "unit_strategy": item.unit_strategy,
        "structure_rules": list(item.structure_rules),
        "expression_rules": list(item.expression_rules),
        "benchmark_features": list(item.benchmark_features),
        "patch_focus": list(item.patch_focus),
        "source_platform": item.source_platform,
        "source_url": item.source_url,
        "hot_dimensions": list(item.hot_dimensions or []),
        "sample_titles": list(item.sample_titles or []),
    }


def build_market_logic_report() -> dict[str, Any]:
    benchmarks = list_track_benchmarks()
    platform_taxonomy = build_platform_taxonomy_report()
    return {
        "source_platform": platform_taxonomy["source_key"],
        "source_url": platform_taxonomy["source_url"],
        "platform_taxonomy": platform_taxonomy,
        "big_categories": sorted({item["big_category"] for item in benchmarks}),
        "sub_categories": [f"{item['big_category']} / {item['sub_category']}" for item in benchmarks],
        "benchmarks": benchmarks,
        "hot_category_summary": list(platform_taxonomy["hot_category_summary"]),
        "sample_titles": [item["title"] for item in platform_taxonomy["sample_titles"]],
        "summary": "先按平台分类和推荐-最热判断受众轴、背景、主题、设定，再按头部结构做内部测试、缺陷补丁与重跑收敛。",
    }


def build_internal_test_plan(max_rounds: int = 3) -> dict[str, Any]:
    return {
        "max_rounds": max_rounds,
        "loop": [
            "先按平台最热分类提炼赛道规则",
            "按赛道规则生成样稿",
            "对照平台热题结构特征做内部评审",
            "输出缺陷清单与补丁方向",
            "更新写作逻辑后重新试跑",
            "达到主要赛道结构要求后停止",
        ],
        "pass_signal": [
            "大类/小类覆盖完整",
            "IP核明确",
            "单元/主线结构成立",
            "表达形式贴近平台最热赛道作品",
        ],
        "rewrite_scope": f"第{CUSTOM_CAMPUS_REWRITE_EPISODE_START}-{CUSTOM_CAMPUS_REWRITE_EPISODE_END}集",
        "rewrite_loop": [
            "writer 先按前三集前情与用户规则生成单集草稿",
            "reviewer 逐条检查细节密度、关系节奏、反派强度与戏核是否成立",
            "decision 只要出现不符合项就打回重写",
            "单集通过后写入验证记录，再继续下一集",
        ],
        "rewrite_pass_signal": [
            "真低谷与公开翻盘都落地",
            "反派压制分层成立，不再只有顾林赫单扛",
            "关系推进符合日常慢热、特殊事件跃迁规则",
            "系统视角严格锁在嘉豪单人认知内",
            "结构不重复，尾钩能把下一集拉起来",
        ],
    }


def _get_expected_emotion_pattern(track: str) -> str:
    """
    根据赛道名称返回预期的情感曲线模式

    Returns:
        模式名称，用于 cnsenti check_emotion_pattern 匹配
    """
    track_lower = track.lower()
    if "追妻火葬场" in track or "追妻" in track:
        return "上升-下降-反弹"  # V形：先负后强正
    elif "逆袭" in track or "打脸" in track:
        return "持续上升"  # 从压抑到爽感爆发
    elif "甜宠" in track or "甜" in track:
        return "波动起伏"  # 持续正情感，偶有小波折
    elif "虐恋" in track or "虐" in track:
        return "上升-下降-反弹"  # 深V：极致虐心后大反转
    else:
        return "波动起伏"  # 默认模式


def score_script_alignment(
    track: str,
    defects: list[str] | None = None,
    strengths: list[str] | None = None,
    round_no: int = 1,
    script_chapters: list[str] | None = None,
) -> dict[str, Any]:
    """
    剧本对齐评分（使用统一评分服务 + 情感曲线分析）

    规则：基础分100，每缺陷扣12分，每优点加4分（上限12），最终[40,98]
    通过条件：缺陷<=1且轮次>=2

    Args:
        track: 赛道名称
        defects: 缺陷清单
        strengths: 优点清单
        round_no: 当前轮次
        script_chapters: 剧本章节列表（用于情感曲线分析）
    """
    from app.services.scoring_service import calculate_score

    defects = defects or []
    strengths = strengths or []

    # 情感曲线分析（如果 cnsenti-skill 可用且有剧本内容）
    cnsenti_tools = _load_cnsenti_tools() if script_chapters else None
    if cnsenti_tools and script_chapters:
        analyze_emotion_curve, check_emotion_pattern = cnsenti_tools
        try:
            full_text = "\n\n".join(script_chapters)
            emotion_result = analyze_emotion_curve(full_text, segment_by="chapter")
            curve = emotion_result.get("curve", [])

            # 根据赛道获取预期情感模式
            expected_pattern = _get_expected_emotion_pattern(track)
            pattern_check = check_emotion_pattern(curve, expected_pattern)
            deviation = pattern_check.get("deviation", 0.0)

            # 根据偏离度添加缺陷/优势（权重：情感维度占评分的15%）
            if deviation > 0.6:
                defects.append(f"情感曲线偏离预期({expected_pattern}) deviation={deviation:.2f}")
            elif deviation > 0.3:
                defects.append(f"情感曲线与赛道模式不完全匹配({expected_pattern})")
            elif deviation < 0.2:
                strengths.append(f"情感曲线贴合赛道模式({expected_pattern})")
        except Exception:
            # 情感分析失败不影响主流程
            pass

    result = calculate_score(
        "script_alignment",
        defects=defects,
        strengths=strengths,
    )

    return {
        "track": track,
        "round": round_no,
        "score": result["score"],
        "passed": result["passed"] and round_no >= 2,
        "defects": defects,
        "strengths": strengths,
        "patch_summary": "；".join(defects[:3]) if defects else "结构与表达基本对齐",
        "scoring_breakdown": result["breakdown"],
    }


def score_episode_rewrite_alignment(review_payload: dict[str, Any], episode_no: int, attempt_no: int) -> dict[str, Any]:
    """
    单集重写对齐评分（使用统一评分服务）

    规则：基础分92，每缺陷扣10分，每优点加3分（上限9），最终[40,98]
    通过条件：decision=="pass"且无缺陷
    """
    from app.services.scoring_service import calculate_score

    strengths = [item.strip() for item in (review_payload.get("strengths") or []) if str(item).strip()]
    defects = [item.strip() for item in (review_payload.get("defects") or []) if str(item).strip()]
    decision = str(review_payload.get("decision") or "").strip().lower()
    if decision not in {"pass", "reject"}:
        decision = "pass" if not defects else "reject"

    # 使用统一评分服务计算
    result = calculate_score(
        "episode_rewrite",
        defects=defects,
        strengths=strengths,
    )

    score = result["score"]
    passed = (decision == "pass") and (len(defects) == 0)

    patch_summary = str(review_payload.get("patch_summary") or "").strip() or ("；".join(defects[:3]) if defects else f"第{episode_no}集本轮通过")
    rerun_reason = str(review_payload.get("rerun_reason") or "").strip() or (f"第{episode_no}集第{attempt_no}轮仍存在{len(defects)}个问题，需要打回重写。" if defects else f"第{episode_no}集第{attempt_no}轮通过，无需重跑。")

    return {
        "episode": episode_no,
        "round": attempt_no,
        "score": score,
        "passed": passed,
        "decision": "approved" if passed else "rejected",
        "defects": defects,
        "strengths": strengths,
        "patch_summary": patch_summary,
        "rerun_reason": rerun_reason,
        "decision_comment": str(review_payload.get("decision_comment") or "").strip(),
        "rule_checks": review_payload.get("rule_checks") or {},
        "scoring_breakdown": result["breakdown"],  # 新增：评分明细
    }


def get_track_benchmark(track: str = DEFAULT_TRACK_KEY) -> dict[str, Any]:
    normalized = track.strip()
    for item in TRACK_BENCHMARKS:
        key = f"{item.big_category} / {item.sub_category}"
        if key == normalized:
            return serialize_track_benchmark(item)
    raise ValueError(f"未知赛道: {track}")


def build_round_defects(track: str, round_no: int) -> list[str]:
    benchmark = get_track_benchmark(track)
    patch_focus = benchmark.get("patch_focus", [])
    if round_no <= 1:
        return patch_focus[:3] or ["结构钩子不够狠", "IP核不够集中"]
    if round_no == 2:
        return patch_focus[1:2] or ["钩子兑现还不够稳定"]
    return []


def build_round_strengths(track: str, round_no: int) -> list[str]:
    benchmark = get_track_benchmark(track)
    features = benchmark.get("benchmark_features", [])
    if round_no <= 1:
        return features[:2]
    if round_no == 2:
        return features[:4]
    return features[:4]


def build_patch_summary(track: str, defects: list[str], round_no: int) -> str:
    benchmark = get_track_benchmark(track)
    if not defects:
        return f"第{round_no}轮已基本收敛，保留{benchmark['sub_category']}赛道的核心表达并锁定前三章结构。"
    return "；".join([f"修补{item}" for item in defects[:3]])


def build_rerun_reason(defects: list[str], round_no: int) -> str:
    if not defects:
        return "本轮已满足内部通过信号，无需重跑。"
    return f"第{round_no}轮仍存在{len(defects)}个关键缺口，需要补齐后重跑。"


def build_sample_payload(track: str, round_no: int) -> dict[str, Any]:
    benchmark = get_track_benchmark(track)
    if track == CUSTOM_CAMPUS_TRACK_KEY:
        return build_custom_campus_sample_payload(round_no)
    chapters = _build_full_three_chapters(benchmark)
    preview = "\n\n".join([
        _chapter_preview("第1章《误伤开局》", chapters[0]),
        _chapter_preview("第2章《抽离反噬》", chapters[1]),
        _chapter_preview("第3章《翻面追击》", chapters[2]),
    ])
    return {
        "title": f"{benchmark['sub_category']}·第{round_no}轮对标样稿",
        "track": track,
        "summary": benchmark["script_summary"],
        "chapters": chapters,
        "sample_preview": preview,
        "chapter_titles": ["误伤开局", "抽离反噬", "翻面追击"],
        "accepted_features": benchmark.get("benchmark_features", [])[:4],
        "ip_core": benchmark.get("ip_core", []),
        "unit_strategy": benchmark.get("unit_strategy", ""),
        "hot_dimensions": benchmark.get("hot_dimensions", []),
        "sample_titles": benchmark.get("sample_titles", []),
    }


def build_custom_campus_sample_payload(
    round_no: int,
    source_payload: dict[str, Any] | None = None,
    dynamic_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmark = get_track_benchmark(CUSTOM_CAMPUS_TRACK_KEY)
    title = (source_payload or {}).get("title") or "重生为嘉豪：我靠装X迎娶软糯校花第一季"
    season_plan = _build_campus_season_plan(source_payload)
    payload_source = dynamic_payload or _build_static_custom_campus_payload(source_payload, round_no)
    chapters = payload_source.get("chapters") or _build_custom_campus_chapters(source_payload, round_no)
    chapter_titles = payload_source.get("chapter_titles") or list(CUSTOM_CAMPUS_CHAPTER_TITLES)
    preview = payload_source.get("sample_preview") or "\n\n".join([
        _chapter_preview(f"第1章《{chapter_titles[0]}》", chapters[0]),
        _chapter_preview(f"第2章《{chapter_titles[1]}》", chapters[1]),
        _chapter_preview(f"第3章《{chapter_titles[2]}》", chapters[2]),
    ])
    return {
        "title": f"{title}·第{round_no}轮对标样稿",
        "track": CUSTOM_CAMPUS_TRACK_KEY,
        "summary": benchmark["script_summary"],
        "chapters": chapters,
        "sample_preview": preview,
        "chapter_titles": chapter_titles,
        "accepted_features": benchmark.get("benchmark_features", [])[:5],
        "ip_core": benchmark.get("ip_core", []),
        "unit_strategy": benchmark.get("unit_strategy", ""),
        "hot_dimensions": benchmark.get("hot_dimensions", []),
        "sample_titles": benchmark.get("sample_titles", []),
        "season_plan": season_plan,
        "season_plan_summary": "第一季共60集，前20集先让嘉豪在极度难堪和围观羞辱里翻身，再把系统、校花线和升学目标拧成一条持续打脸主线；中20集围绕考试与觉醒连续反杀；后20集完成八道口技能学院录取。",
        "meme_hit_points": [
            "厕所醒来先被资格卡喉，再把社死翻成存在感武器",
            "希沃白板亮牌装股神，把笑场硬拧成围观场",
            "系统把装X现场变成限时任务，还会当场毒舌施压",
            "校花先看见伤口，再看见翻盘，关系从怜悯转向好奇",
            "围观群众从等他出丑，转成盯着他会不会真的赢",
        ],
        "romance_progress": "李梓沐先看见嘉豪被踩在底层的狼狈，再看见他硬顶着翻盘，前三章完成从同情到注意的跃迁。",
        "campus_face_slap_density": "前三章每章都必须有一次公开围观翻面，并把系统兑现、资格危机和校花线绑在同一条推进链上。",
        "generation_mode": payload_source.get("generation_mode", "platform_rule_regeneration"),
        "rule_basis": payload_source.get("rule_basis", "novelquickapp_hot_category"),
        "generation_context": payload_source.get("generation_context", {}),
        "generation_error": payload_source.get("generation_error") or "",
    }


async def build_dynamic_custom_campus_sample_payload(
    round_no: int,
    source_payload: dict[str, Any] | None = None,
    selected_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        dynamic_payload = await _generate_custom_campus_dynamic_payload(source_payload, round_no, selected_materials)
    except Exception as exc:
        dynamic_payload = _build_static_custom_campus_payload(source_payload, round_no)
        dynamic_payload["generation_mode"] = "static_fallback_after_generation_failure"
        dynamic_payload["generation_error"] = str(exc)
    return build_custom_campus_sample_payload(round_no, source_payload, dynamic_payload=dynamic_payload)


async def build_dynamic_custom_campus_rewrite_payload(
    source_payload: dict[str, Any] | None = None,
    selected_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        return await _generate_custom_campus_rewrite_payload(source_payload, selected_materials)
    except Exception as exc:
        fallback_episodes = _build_episode_rewrite_fallback(source_payload, str(exc))
        return {
            "title": f"{(source_payload or {}).get('title') or '重生为嘉豪：我靠装X迎娶软糯校花第一季'}·第5-10集重写稿",
            "track": CUSTOM_CAMPUS_TRACK_KEY,
            "summary": "第5-10集动态重写降级稿。",
            "accepted_features": [],
            "sample_preview": "第5-10集动态重写失败，已降级为最近可用版本摘要。",
            "chapter_titles": [item["title"] for item in fallback_episodes],
            "chapters": [item["body"] for item in fallback_episodes],
            "rewrite_episodes": fallback_episodes,
            "generation_mode": "episode_rewrite_static_fallback",
            "rule_basis": "novelquickapp_hot_category_with_user_rules",
            "generation_context": {"fallback": True},
            "generation_error": str(exc),
        }


def _build_static_custom_campus_payload(source_payload: dict[str, Any] | None, round_no: int) -> dict[str, Any]:
    chapters = _build_custom_campus_chapters(source_payload, round_no)
    chapter_titles = list(CUSTOM_CAMPUS_CHAPTER_TITLES)
    preview = "\n\n".join([
        _chapter_preview(f"第1章《{chapter_titles[0]}》", chapters[0]),
        _chapter_preview(f"第2章《{chapter_titles[1]}》", chapters[1]),
        _chapter_preview(f"第3章《{chapter_titles[2]}》", chapters[2]),
    ])
    return {
        "chapters": chapters,
        "chapter_titles": chapter_titles,
        "sample_preview": preview,
        "generation_mode": "platform_rule_regeneration",
        "rule_basis": "novelquickapp_hot_category",
        "generation_context": {},
        "generation_error": "",
    }



async def _generate_custom_campus_dynamic_payload(
    source_payload: dict[str, Any] | None,
    round_no: int,
    selected_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    benchmark = get_track_benchmark(CUSTOM_CAMPUS_TRACK_KEY)
    platform_taxonomy = build_platform_taxonomy_report()
    generation_vars = _build_custom_generation_variables(source_payload, benchmark, platform_taxonomy, selected_materials)
    beat_sheet_result = await _generate_beat_sheet(generation_vars)

    chapters: list[str] = []
    script_contexts: list[dict[str, Any]] = []
    for draft_episode in range(1, DYNAMIC_CUSTOM_EPISODE_COUNT + 1):
        scene_list_result = await _generate_scene_list(generation_vars, beat_sheet_result, draft_episode)
        script_result = await _generate_script_draft(generation_vars, scene_list_result, draft_episode)
        chapters.append(_normalize_script_markdown(script_result.get("full_output", ""), draft_episode))
        script_contexts.append({
            "episode": draft_episode,
            "context_output": script_result.get("context_output", ""),
        })

    return {
        "chapters": chapters,
        "chapter_titles": list(CUSTOM_CAMPUS_CHAPTER_TITLES),
        "sample_preview": "\n\n".join([
            _chapter_preview(f"第1章《{CUSTOM_CAMPUS_CHAPTER_TITLES[0]}》", chapters[0]),
            _chapter_preview(f"第2章《{CUSTOM_CAMPUS_CHAPTER_TITLES[1]}》", chapters[1]),
            _chapter_preview(f"第3章《{CUSTOM_CAMPUS_CHAPTER_TITLES[2]}》", chapters[2]),
        ]),
        "generation_mode": "dynamic_prompt_regeneration",
        "rule_basis": "novelquickapp_hot_category",
        "generation_context": {
            "beat_sheet_context": beat_sheet_result.get("context_output", ""),
            "episode_contexts": script_contexts,
        },
        "generation_error": "",
    }


async def _generate_custom_campus_rewrite_payload(
    source_payload: dict[str, Any] | None = None,
    selected_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    episodes = await _generate_custom_campus_episode_rewrites(source_payload, selected_materials)
    accepted = [item for item in episodes if item.get("passed")]
    preview_lines = [f"第{item['episode']}集《{item['title']}》：{item.get('summary') or item.get('decision_comment') or ''}" for item in episodes]
    return {
        "title": f"{(source_payload or {}).get('title') or '重生为嘉豪：我靠装X迎娶软糯校花第一季'}·第5-10集动态重写稿",
        "track": CUSTOM_CAMPUS_TRACK_KEY,
        "summary": "围绕第5-10集逐集执行 writer-reviewer-decision 闭环后的通过稿。",
        "accepted_features": [
            "逐集多轮打回重写",
            "强反派分层压制",
            "关系慢推与特殊事件跃迁并行",
            "系统认知边界严格锁定",
            "第4集质感基线回收",
        ],
        "sample_preview": "\n".join(preview_lines),
        "chapter_titles": [item["title"] for item in accepted],
        "chapters": [item["body"] for item in accepted],
        "rewrite_episodes": episodes,
        "generation_mode": "episode_rewrite_multi_agent_loop",
        "rule_basis": "novelquickapp_hot_category_with_user_rules",
        "generation_context": {
            "episode_range": f"{CUSTOM_CAMPUS_REWRITE_EPISODE_START}-{CUSTOM_CAMPUS_REWRITE_EPISODE_END}",
            "accepted_count": len(accepted),
            "attempt_limit": CUSTOM_CAMPUS_REWRITE_MAX_ATTEMPTS,
        },
        "generation_error": "",
    }


def _build_custom_generation_variables(
    source_payload: dict[str, Any] | None,
    benchmark: dict[str, Any],
    platform_taxonomy: dict[str, Any],
    selected_materials: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    source_payload = source_payload or {}
    project_brief = source_payload.get("project_brief") or {}
    story_bible = _resolve_story_bible(source_payload)
    hot_signal = platform_taxonomy.get("hot_signal") or {}
    dimensions = platform_taxonomy.get("dimensions") or {}
    rule_profile_lines = [
        f"平台：{platform_taxonomy.get('platform_name') or '红果短剧'}",
        f"来源：{platform_taxonomy.get('source_url') or ''}",
        f"热度入口：{hot_signal.get('dimension') or '推荐'} -> {' / '.join(hot_signal.get('priority') or []) or '最热'}",
        f"赛道：{CUSTOM_CAMPUS_TRACK_KEY}",
        f"IP核：{'、'.join(benchmark.get('ip_core') or [])}",
        f"结构规则：{'；'.join(benchmark.get('structure_rules') or [])}",
        f"表达规则：{'；'.join(benchmark.get('expression_rules') or [])}",
        f"热门背景：{'、'.join((dimensions.get('背景') or [])[:8])}",
        f"热门设定：{'、'.join((dimensions.get('设定') or [])[:10])}",
    ]
    constraints_lines = [
        "只写中文。",
        "必须是可拍、可演、可继续拆分镜的短剧/2D漫剧剧本。",
        "前三集必须出现厕所、教室白板、围观公开翻盘、校花注意、系统毒舌施压。",
        "每集都要有公开后果，不能只写内心。",
        "不要解释创作过程，不要输出额外说明。",
    ]
    concept = project_brief.get("outline") or source_payload.get("source_summary") or benchmark.get("script_summary") or ""
    characters = _build_story_bible_character_sheet(story_bible) or project_brief.get("characters") or _build_default_character_sheet(source_payload)
    world_rules = _build_story_bible_world_rules(story_bible)
    relationship_guardrails = _build_story_bible_relationship_guardrails(story_bible)
    golden_finger_rules = _build_story_bible_golden_finger_rules(story_bible)
    conflict_plan = _build_story_bible_conflict_plan(story_bible)
    material_references = _build_selected_material_reference(selected_materials)
    material_borrow_focus = _build_selected_material_borrow_focus(selected_materials)
    material_risk_guardrails = _build_selected_material_risk_guardrails(selected_materials)
    material_heat_signals = _build_selected_material_heat_signals(selected_materials)
    material_do_not_copy = _build_selected_material_do_not_copy(selected_materials)

    return {
        "project_type": "短剧 / 2D漫剧",
        "episode_count": str(DYNAMIC_CUSTOM_EPISODE_COUNT),
        "episode_minutes": str(DYNAMIC_CUSTOM_EPISODE_MINUTES),
        "audience_axis": benchmark.get("audience_axis") or "male",
        "genre_main": benchmark.get("big_category") or "男频逆袭",
        "genre_sub": benchmark.get("sub_category") or "校园系统装X",
        "rule_profile": "\n".join(f"- {line}" for line in rule_profile_lines if line),
        "constraints": "\n".join(f"- {line}" for line in constraints_lines),
        "concept": concept,
        "characters": characters,
        "world_rules": world_rules,
        "relationship_guardrails": relationship_guardrails,
        "golden_finger_rules": golden_finger_rules,
        "conflict_plan": conflict_plan,
        "material_references": material_references,
        "material_borrow_focus": material_borrow_focus,
        "material_risk_guardrails": material_risk_guardrails,
        "material_heat_signals": material_heat_signals,
        "material_do_not_copy": material_do_not_copy,
    }


def _build_selected_material_reference(selected_materials: list[dict[str, Any]] | None) -> str:
    if not selected_materials:
        return "- 无已召回素材。"

    lines: list[str] = []
    for index, item in enumerate(selected_materials[:3], start=1):
        raw_payload = item.get("raw_payload") or {}
        borrow_points = raw_payload.get("borrow_points") or []
        risk_points = raw_payload.get("risk_points") or []
        data_points = item.get("data_points") or []
        data_text = "；".join(
            json.dumps(point, ensure_ascii=False) if isinstance(point, (dict, list)) else str(point)
            for point in data_points[:3]
            if point is not None and str(point).strip()
        ) or "无"
        lines.extend([
            f"- 素材{index}：{item.get('title') or '未命名素材'}｜平台 {item.get('source_platform') or 'unknown'}｜热度分 {item.get('heat_score') or 0}",
            f"  - 结构标签：{'、'.join(item.get('structure_tags') or []) or '无'}",
            f"  - 风格标签：{'、'.join(item.get('style_tags') or []) or '无'}",
            f"  - 项目适配：{'、'.join(item.get('project_fit_tags') or []) or '无'}",
            f"  - 爆火原因：{item.get('heat_reason') or '无'}",
            f"  - 数据线索：{data_text}",
            f"  - 可借鉴点：{'；'.join(str(point) for point in borrow_points[:4] if str(point).strip()) or '无'}",
            f"  - 风险提示：{'；'.join(str(point) for point in risk_points[:4] if str(point).strip()) or '无'}",
            "  - 使用原则：只能借结构、节奏、公开反馈与钩子设计，不能照搬具体剧情、角色名、台词和独有设定。",
        ])
    return "\n".join(lines)


def _build_selected_material_borrow_focus(selected_materials: list[dict[str, Any]] | None) -> str:
    if not selected_materials:
        return "- 无额外借鉴重点。"
    lines: list[str] = []
    for index, item in enumerate(selected_materials[:3], start=1):
        borrow_points = ((item.get("raw_payload") or {}).get("borrow_points") or [])[:4]
        if borrow_points:
            lines.append(f"- 素材{index}《{item.get('title') or '未命名素材'}》：{'；'.join(str(point) for point in borrow_points if str(point).strip())}")
    return "\n".join(lines) or "- 无额外借鉴重点。"


def _build_selected_material_risk_guardrails(selected_materials: list[dict[str, Any]] | None) -> str:
    if not selected_materials:
        return "- 无额外风险提醒。"
    lines: list[str] = []
    for index, item in enumerate(selected_materials[:3], start=1):
        risk_points = ((item.get("raw_payload") or {}).get("risk_points") or [])[:4]
        if risk_points:
            lines.append(f"- 素材{index}《{item.get('title') or '未命名素材'}》：{'；'.join(str(point) for point in risk_points if str(point).strip())}")
    return "\n".join(lines) or "- 无额外风险提醒。"


def _build_selected_material_heat_signals(selected_materials: list[dict[str, Any]] | None) -> str:
    if not selected_materials:
        return "- 无额外热度信号。"
    lines = [
        f"- 《{item.get('title') or '未命名素材'}》：热度分 {item.get('heat_score') or 0}；爆火原因 {item.get('heat_reason') or '无'}"
        for item in selected_materials[:3]
    ]
    return "\n".join(lines) or "- 无额外热度信号。"


def _build_selected_material_do_not_copy(selected_materials: list[dict[str, Any]] | None) -> str:
    if not selected_materials:
        return "- 不得照搬外部素材的具体剧情、角色名、台词和独有设定。"
    lines = [
        "- 不得照搬外部素材的具体剧情、角色名、台词和独有设定。",
        "- 不得把外部素材的一整条冲突链原样平移到当前项目。",
        "- 借鉴只允许落在结构、节奏、公开反馈机制、空间调度和钩子设计。",
    ]
    for item in selected_materials[:2]:
        lines.append(f"- 《{item.get('title') or '未命名素材'}》只能参考其热度机制与结构打法，不能复刻人物关系和关键事件。")
    return "\n".join(lines)


def _resolve_story_bible(source_payload: dict[str, Any] | None) -> dict[str, Any]:
    source_payload = source_payload or {}
    existing = source_payload.get("story_bible")
    if isinstance(existing, dict) and existing:
        return existing
    return build_story_bible(mode="extract_and_expand", source_payload=source_payload)


def _build_story_bible_character_sheet(story_bible: dict[str, Any]) -> str:
    items = story_bible.get("character_bible") or []
    if not items:
        return ""
    lines = []
    for item in items[:6]:
        lines.append(
            "- {name}｜身份 {identity}｜目标 {goal}｜弱点 {weakness}｜说话方式 {speaking_style}｜秘密 {secret}｜弧线 {arc}".format(
                name=item.get("name") or "未命名角色",
                identity=item.get("identity") or "待补全",
                goal=item.get("goal") or "待补全",
                weakness=item.get("weakness") or "待补全",
                speaking_style=item.get("speaking_style") or "待补全",
                secret=item.get("secret") or "待补全",
                arc=item.get("arc") or "待补全",
            )
        )
    return "\n".join(lines)


def _build_story_bible_world_rules(story_bible: dict[str, Any]) -> str:
    world_bible = story_bible.get("world_bible") or {}
    rules = world_bible.get("rules") or []
    constraints = world_bible.get("constraints") or []
    lines = []
    if world_bible.get("setting"):
        lines.append(f"- 世界设定：{world_bible.get('setting')}")
    lines.extend(f"- 世界规则：{str(rule).strip()}" for rule in rules[:5] if str(rule).strip())
    lines.extend(f"- 世界限制：{str(rule).strip()}" for rule in constraints[:4] if str(rule).strip())
    return "\n".join(lines) or "- 暂无额外世界观规则。"


def _build_story_bible_relationship_guardrails(story_bible: dict[str, Any]) -> str:
    matrix = story_bible.get("relationship_matrix") or []
    if not matrix:
        return "- 暂无额外关系护栏。"
    lines = []
    for item in matrix[:6]:
        lines.append(
            f"- {item.get('pair') or '角色关系'}｜当前状态 {item.get('current_state') or '待补全'}｜推进上限 {item.get('ceiling') or '待补全'}｜冲突点 {item.get('conflict') or '待补全'}"
        )
    return "\n".join(lines)


def _build_story_bible_golden_finger_rules(story_bible: dict[str, Any]) -> str:
    golden_finger = story_bible.get("golden_finger_bible") or {}
    if not golden_finger:
        return "- 暂无额外金手指规则。"
    return "\n".join([
        f"- 是否存在：{'是' if golden_finger.get('exists') else '否'}",
        f"- 来源：{golden_finger.get('origin') or '无'}",
        f"- 触发条件：{golden_finger.get('trigger') or '无'}",
        f"- 收益：{golden_finger.get('benefit') or '无'}",
        f"- 代价：{golden_finger.get('cost') or '无'}",
        f"- 升级路径：{golden_finger.get('upgrade_path') or '无'}",
    ])


def _build_story_bible_conflict_plan(story_bible: dict[str, Any]) -> str:
    conflict_map = story_bible.get("conflict_map") or {}
    stage_conflicts = conflict_map.get("stage_conflicts") or []
    antagonist_pressure = conflict_map.get("antagonist_pressure") or []
    lines = []
    if conflict_map.get("main_conflict"):
        lines.append(f"- 主线冲突：{conflict_map.get('main_conflict')}")
    lines.extend(f"- 阶段冲突：{str(item).strip()}" for item in stage_conflicts[:5] if str(item).strip())
    lines.extend(f"- 反派压力：{str(item).strip()}" for item in antagonist_pressure[:5] if str(item).strip())
    return "\n".join(lines) or "- 暂无额外冲突规划。"


def _build_fixed_memory_block(source_payload: dict[str, Any] | None, story_bible: dict[str, Any]) -> str:
    project_brief = (source_payload or {}).get("project_brief") or {}
    lines = [
        f"- 项目标题：{project_brief.get('title') or (source_payload or {}).get('title') or '未命名项目'}",
        f"- 核心大纲：{project_brief.get('outline') or (source_payload or {}).get('source_summary') or '待补全'}",
        "- 写作原则：人物目标不能漂移，关系慢推，特殊事件才允许跃迁，控字数靠切集，不靠压扁细节。",
        "- 质量底线：必须保留细节密度、现场反应、可拍动作、明确后果，不能写成功能性梗概。",
    ]
    lines.append(f"- 角色锚点：{_flatten_memory_line(_build_story_bible_character_sheet(story_bible), limit=4)}")
    lines.append(f"- 世界/规则锚点：{_flatten_memory_line(_build_story_bible_world_rules(story_bible), limit=4)}")
    lines.append(f"- 关系锚点：{_flatten_memory_line(_build_story_bible_relationship_guardrails(story_bible), limit=4)}")
    lines.append(f"- 金手指锚点：{_flatten_memory_line(_build_story_bible_golden_finger_rules(story_bible), limit=4)}")
    lines.append(f"- 冲突锚点：{_flatten_memory_line(_build_story_bible_conflict_plan(story_bible), limit=4)}")
    return "\n".join(lines)


def _build_phase_memory_block(source_payload: dict[str, Any] | None, episode_no: int, accepted_episodes: list[dict[str, Any]] | None = None) -> str:
    source_payload = source_payload or {}
    accepted_episodes = accepted_episodes or []
    season_plan = source_payload.get("season_plan") or _build_campus_season_plan(source_payload)
    current_phase = next(
        (
            item
            for item in season_plan
            if int(item.get("start_episode") or 0) <= episode_no <= int(item.get("end_episode") or 0)
        ),
        None,
    )
    phase_recent = [item for item in accepted_episodes if abs(int(item.get("episode") or 0) - episode_no) <= 2]
    lines = []
    if current_phase:
        lines.extend([
            f"- 当前阶段：第{current_phase.get('start_episode')}-{current_phase.get('end_episode')}集《{current_phase.get('arc_title') or '阶段推进'}》",
            f"- 阶段目标：{current_phase.get('goal') or '保持主线推进'}",
            f"- 阶段尾钩：{current_phase.get('hook') or '抬高下一阶段压力'}",
        ])
    else:
        lines.append("- 当前阶段：未命中分段，按主线推进。")
    lines.append(f"- 本集硬目标：{_episode_target_instruction(episode_no)}")
    if phase_recent:
        lines.append(
            "- 阶段内最近通过集：" + "；".join(
                f"第{item['episode']}集《{item['title']}》{item.get('summary') or item.get('decision_comment') or ''}"
                for item in phase_recent[-3:]
            )
        )
    else:
        lines.append("- 阶段内最近通过集：暂无。")
    lines.append("- 阶段禁忌：不要重复同构公开打脸；不要把关系推进写成突然倒向；不要把高位压制重新压扁成单一同辈冲突。")
    return "\n".join(lines)


def _build_episode_memory_block(previous_summary: str, accepted_episodes: list[dict[str, Any]] | None, episode_no: int) -> str:
    accepted_episodes = accepted_episodes or []
    lines = [f"- 直接前情：{_flatten_memory_line(previous_summary, limit=6)}"]
    if accepted_episodes:
        latest = accepted_episodes[-1]
        lines.append(
            f"- 最近一集：第{latest['episode']}集《{latest['title']}》{latest.get('summary') or latest.get('decision_comment') or ''}"
        )
    else:
        lines.append("- 最近一集：暂无后续通过集。")
    lines.append(f"- 本集必须承接：{_episode_target_instruction(episode_no)}")
    lines.append("- 本集必保：真低谷、公开后果、围观反馈、至少一次局势翻动、清晰集末钩子。")
    return "\n".join(lines)


def _flatten_memory_line(text: str, limit: int = 4) -> str:
    lines = [line.strip().lstrip("-").strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return "无"
    return "；".join(lines[:limit])


def _build_phase_review_focus(episode_no: int, accepted_episodes: list[dict[str, Any]] | None = None) -> str:
    accepted_episodes = accepted_episodes or []
    latest_titles = "、".join(
        f"第{item['episode']}集《{item['title']}》"
        for item in accepted_episodes[-3:]
    ) or "暂无后续通过集"
    return "\n".join([
        f"- 当前审查重点集：第{episode_no}集",
        f"- 对照最近已通过集：{latest_titles}",
        "- 必查长线稳定：关系是否偷跑、反派层级是否被写扁、系统规则是否松动、旧伏笔是否被无故跳过。",
        "- 必查观感稳定：细节密度是否下降、动作/对白是否变粗、围观场和尾钩是否与前集同构。",
    ])


async def _generate_custom_campus_episode_rewrites(
    source_payload: dict[str, Any] | None,
    selected_materials: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source_payload = source_payload or {}
    story_bible = _resolve_story_bible(source_payload)
    previous_summary = _build_existing_episode_context(source_payload)
    fixed_memory = _build_fixed_memory_block(source_payload, story_bible)
    episodes: list[dict[str, Any]] = []
    for episode_no in range(CUSTOM_CAMPUS_REWRITE_EPISODE_START, CUSTOM_CAMPUS_REWRITE_EPISODE_END + 1):
        phase_memory = _build_phase_memory_block(source_payload, episode_no, episodes)
        episode_memory = _build_episode_memory_block(previous_summary, episodes, episode_no)
        result = await _run_single_episode_rewrite_loop(
            source_payload,
            previous_summary,
            episodes,
            episode_no,
            selected_materials,
            fixed_memory=fixed_memory,
            phase_memory=phase_memory,
            episode_memory=episode_memory,
        )
        episodes.append(result)
        previous_summary += f"\n第{episode_no}集《{result['title']}》：{result.get('summary') or result.get('decision_comment') or ''}"
    return episodes


async def _run_single_episode_rewrite_loop(
    source_payload: dict[str, Any] | None,
    previous_summary: str,
    accepted_episodes: list[dict[str, Any]],
    episode_no: int,
    selected_materials: list[dict[str, Any]] | None = None,
    *,
    fixed_memory: str = "",
    phase_memory: str = "",
    episode_memory: str = "",
) -> dict[str, Any]:
    last_rewrite_payload: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    for attempt_no in range(1, CUSTOM_CAMPUS_REWRITE_MAX_ATTEMPTS + 1):
        rewrite_payload = await _generate_single_episode_rewrite(
            source_payload=source_payload,
            previous_summary=previous_summary,
            accepted_episodes=accepted_episodes,
            episode_no=episode_no,
            attempt_no=attempt_no,
            prior_feedback=history,
            selected_materials=selected_materials,
            fixed_memory=fixed_memory,
            phase_memory=phase_memory,
            episode_memory=episode_memory,
        )
        review_payload = await _review_single_episode_rewrite(
            source_payload=source_payload,
            previous_summary=previous_summary,
            accepted_episodes=accepted_episodes,
            rewrite_payload=rewrite_payload,
            episode_no=episode_no,
            attempt_no=attempt_no,
            selected_materials=selected_materials,
            fixed_memory=fixed_memory,
            phase_memory=phase_memory,
            episode_memory=episode_memory,
        )
        decision_payload = score_episode_rewrite_alignment(review_payload, episode_no, attempt_no)
        loop_entry = {
            "attempt": attempt_no,
            "title": rewrite_payload.get("title") or f"第{episode_no}集",
            "summary": rewrite_payload.get("summary") or "",
            "strengths": decision_payload["strengths"],
            "defects": decision_payload["defects"],
            "patch_summary": decision_payload["patch_summary"],
            "decision": decision_payload["decision"],
            "score": decision_payload["score"],
        }
        history.append(loop_entry)
        rewrite_payload.update({
            "attempt": attempt_no,
            "review": decision_payload,
            "passed": decision_payload["passed"],
        })
        last_rewrite_payload = rewrite_payload
        if decision_payload["passed"]:
            return {
                "episode": episode_no,
                "title": rewrite_payload.get("title") or f"第{episode_no}集",
                "body": _normalize_episode_script(rewrite_payload.get("body", ""), episode_no),
                "summary": rewrite_payload.get("summary") or "",
                "attempts": attempt_no,
                "passed": True,
                "score": decision_payload["score"],
                "strengths": decision_payload["strengths"],
                "defects": decision_payload["defects"],
                "patch_summary": decision_payload["patch_summary"],
                "rerun_reason": decision_payload["rerun_reason"],
                "decision_comment": decision_payload["decision_comment"],
                "rule_checks": decision_payload["rule_checks"],
                "history": history,
            }
    fallback_payload = last_rewrite_payload or {
        "title": f"第{episode_no}集",
        "body": _fallback_episode_body(episode_no),
        "summary": "动态重写失败，降级为占位稿。",
    }
    last_review = (last_rewrite_payload or {}).get("review") or {
        "score": 40,
        "strengths": [],
        "defects": ["达到重试上限，仍未通过决策校验"],
        "patch_summary": "需要人工继续重写",
        "rerun_reason": "达到重试上限",
        "decision_comment": "仍有关键问题未收敛。",
        "rule_checks": {},
    }
    return {
        "episode": episode_no,
        "title": fallback_payload.get("title") or f"第{episode_no}集",
        "body": _normalize_episode_script(fallback_payload.get("body", ""), episode_no),
        "summary": fallback_payload.get("summary") or "",
        "attempts": CUSTOM_CAMPUS_REWRITE_MAX_ATTEMPTS,
        "passed": False,
        "score": last_review["score"],
        "strengths": last_review["strengths"],
        "defects": last_review["defects"],
        "patch_summary": last_review["patch_summary"],
        "rerun_reason": last_review["rerun_reason"],
        "decision_comment": last_review["decision_comment"],
        "rule_checks": last_review["rule_checks"],
        "history": history,
    }


async def _generate_single_episode_rewrite(
    source_payload: dict[str, Any] | None,
    previous_summary: str,
    accepted_episodes: list[dict[str, Any]],
    episode_no: int,
    attempt_no: int,
    prior_feedback: list[dict[str, Any]],
    selected_materials: list[dict[str, Any]] | None = None,
    *,
    fixed_memory: str = "",
    phase_memory: str = "",
    episode_memory: str = "",
) -> dict[str, Any]:
    from app.config import config
    prompt = _build_episode_writer_prompt(
        source_payload,
        previous_summary,
        accepted_episodes,
        episode_no,
        attempt_no,
        prior_feedback,
        selected_materials,
        fixed_memory=fixed_memory,
        phase_memory=phase_memory,
        episode_memory=episode_memory,
    )

    # 获取生成配置
    gen_config = getattr(config, 'text_generation', {}) or {}

    result = await generate_json(
        provider=gen_config.get('provider', 'openai'),
        base_url=gen_config.get('base_url', 'https://api.openai.com'),
        api_key=gen_config.get('api_key', ''),
        model=gen_config.get('model', 'gpt-4'),
        prompt=prompt,
        system_prompt="你是校园男频短剧 writer agent。你只输出一个 JSON 对象，不要解释。",
        temperature=0.7,
        max_tokens=4000,
    )

    payload = result if isinstance(result, dict) else {}
    title = str(payload.get("title") or CUSTOM_CAMPUS_REWRITE_TITLE_HINTS.get(episode_no) or f"第{episode_no}集").strip()
    summary = _coerce_generation_text(payload.get("summary"))
    body = _coerce_generation_text(payload.get("body"))
    if not summary or not body:
        raise ValueError(f"第{episode_no}集 writer 返回缺少 summary/body")
    return {"title": title, "summary": summary, "body": body}


async def _review_single_episode_rewrite(
    source_payload: dict[str, Any] | None,
    previous_summary: str,
    accepted_episodes: list[dict[str, Any]],
    rewrite_payload: dict[str, Any],
    episode_no: int,
    attempt_no: int,
    selected_materials: list[dict[str, Any]] | None = None,
    *,
    fixed_memory: str = "",
    phase_memory: str = "",
    episode_memory: str = "",
) -> dict[str, Any]:
    from app.config import config
    prompt = _build_episode_reviewer_prompt(
        source_payload,
        previous_summary,
        accepted_episodes,
        rewrite_payload,
        episode_no,
        attempt_no,
        selected_materials,
        fixed_memory=fixed_memory,
        phase_memory=phase_memory,
        episode_memory=episode_memory,
    )

    # 获取生成配置
    gen_config = getattr(config, 'text_generation', {}) or {}

    result = await generate_json(
        provider=gen_config.get('provider', 'openai'),
        base_url=gen_config.get('base_url', 'https://api.openai.com'),
        api_key=gen_config.get('api_key', ''),
        model=gen_config.get('model', 'gpt-4'),
        prompt=prompt,
        system_prompt="你是校园男频短剧 reviewer + decision agent。你只输出一个 JSON 对象，不要解释。",
        temperature=0.2,
        max_tokens=4000,
    )

    return result if isinstance(result, dict) else {}


def _build_episode_writer_prompt(
    source_payload: dict[str, Any] | None,
    previous_summary: str,
    accepted_episodes: list[dict[str, Any]],
    episode_no: int,
    attempt_no: int,
    prior_feedback: list[dict[str, Any]],
    selected_materials: list[dict[str, Any]] | None = None,
    *,
    fixed_memory: str = "",
    phase_memory: str = "",
    episode_memory: str = "",
) -> str:
    project_brief = (source_payload or {}).get("project_brief") or {}
    story_bible = _resolve_story_bible(source_payload)
    accepted_summary = "\n".join(
        f"- 第{item['episode']}集《{item['title']}》：{item.get('summary') or item.get('decision_comment') or ''}"
        for item in accepted_episodes[-3:]
    ) or "- 暂无已通过的后续集。"
    feedback_block = "\n".join(
        f"- 第{item['attempt']}轮被打回：问题 {('；'.join(item.get('defects') or []) or '无')}；补丁 {item.get('patch_summary') or '无'}"
        for item in prior_feedback[-2:]
    ) or "- 首轮，无历史打回。"
    story_bible_characters = _build_story_bible_character_sheet(story_bible)
    story_bible_world_rules = _build_story_bible_world_rules(story_bible)
    story_bible_relationship_guardrails = _build_story_bible_relationship_guardrails(story_bible)
    story_bible_golden_finger_rules = _build_story_bible_golden_finger_rules(story_bible)
    story_bible_conflict_plan = _build_story_bible_conflict_plan(story_bible)
    material_reference = _build_selected_material_reference(selected_materials)
    material_borrow_focus = _build_selected_material_borrow_focus(selected_materials)
    material_risk_guardrails = _build_selected_material_risk_guardrails(selected_materials)
    material_heat_signals = _build_selected_material_heat_signals(selected_materials)
    material_do_not_copy = _build_selected_material_do_not_copy(selected_materials)
    return f'''请写《{project_brief.get("title") or "重生为嘉豪：我靠装X迎娶软糯校花第一季"}》第{episode_no}集。

输出要求：
1. 只输出一个 JSON 对象，字段必须是 title、summary、body。
2. body 必须是标准短剧/2D漫剧对白格式：每场用【场X：地点/时间】开头，下一行写人物：，动作用△独立成行，对白用“角色名：台词”，系统只允许写 SYS:，内心只允许写 OS:。
3. 单集必须围绕一个主戏核，不要拼贴多个小事件。
4. 每集都必须有真低谷、公开后果、公开围观、反压或翻盘、集末钩子。
5. 细节密度要回到第4集质感：多写动作停顿、微反应、现场氛围，不要写成梗概。
6. 日常关系推进只能小步走；只有高强度特殊事件才允许关系跃迁。李梓沐不能突然倒向嘉豪。
7. 李泽言绝不能知道系统存在；系统任务、奖励、毒舌，只能出现在嘉豪单人视角。
8. 反派必须分层：顾林赫负责同辈前线压制，但更高位压制要逐步由顾林臻、何院长、父辈旧案、规则/资格层面接管。
9. 第7-9集绝不能重复“设备栽赃-翻案”模板；每集戏核都要不同。
10. 保持校园男频、短句、可拍、硬碰硬、公开奖惩立刻兑现。
11. 下方素材只能借结构、节奏、公开反馈、热度机制与爆点设计，不能照搬具体剧情、角色名、台词和独有设定。
12. 必须遵守前置设定层：角色目标与弱点不能漂移，关系推进不能突破关系护栏，金手指必须按触发条件、收益、代价和暴露风险执行。
13. 本轮采用三层记忆：固定层不能丢，阶段层不能乱，单集层必须直接承接；宁可少写一点，也不能把长线写塌。
14. 本集必须同时保证剧情稳定和细节质感，不能只顾推进事件而牺牲动作细节、反应细节和现场氛围。

固定层记忆：
{fixed_memory or '- 暂无固定层记忆。'}

阶段层记忆：
{phase_memory or '- 暂无阶段层记忆。'}

单集层记忆：
{episode_memory or '- 暂无单集层记忆。'}

前三集与前情摘要：
{previous_summary}

最近已通过集摘要：
{accepted_summary}

本集硬目标：
{_episode_target_instruction(episode_no)}

历史打回反馈：
{feedback_block}

前置设定-角色库：
{story_bible_characters}

前置设定-世界观规则：
{story_bible_world_rules}

前置设定-关系护栏：
{story_bible_relationship_guardrails}

前置设定-金手指规则：
{story_bible_golden_finger_rules}

前置设定-冲突规划：
{story_bible_conflict_plan}

素材参考：
{material_reference}

素材借鉴重点：
{material_borrow_focus}

热度信号：
{material_heat_signals}

风险护栏：
{material_risk_guardrails}

禁止照搬：
{material_do_not_copy}

原稿大纲：
{project_brief.get("outline") or (source_payload or {}).get("source_summary") or "无"}

人物设定：
{story_bible_characters or project_brief.get("characters") or _build_default_character_sheet(source_payload)}
'''


def _build_episode_reviewer_prompt(
    source_payload: dict[str, Any] | None,
    previous_summary: str,
    accepted_episodes: list[dict[str, Any]],
    rewrite_payload: dict[str, Any],
    episode_no: int,
    attempt_no: int,
    selected_materials: list[dict[str, Any]] | None = None,
    *,
    fixed_memory: str = "",
    phase_memory: str = "",
    episode_memory: str = "",
) -> str:
    story_bible = _resolve_story_bible(source_payload)
    accepted_summary = "\n".join(
        f"- 第{item['episode']}集《{item['title']}》：{item.get('summary') or item.get('decision_comment') or ''}"
        for item in accepted_episodes[-3:]
    ) or "- 暂无已通过的后续集。"
    story_bible_world_rules = _build_story_bible_world_rules(story_bible)
    story_bible_relationship_guardrails = _build_story_bible_relationship_guardrails(story_bible)
    story_bible_golden_finger_rules = _build_story_bible_golden_finger_rules(story_bible)
    story_bible_conflict_plan = _build_story_bible_conflict_plan(story_bible)
    material_reference = _build_selected_material_reference(selected_materials)
    material_risk_guardrails = _build_selected_material_risk_guardrails(selected_materials)
    material_do_not_copy = _build_selected_material_do_not_copy(selected_materials)
    phase_review_focus = _build_phase_review_focus(episode_no, accepted_episodes)
    return f'''请你作为 reviewer 和 decision agent，审查下面这版第{episode_no}集是否通过。

输出必须是一个 JSON 对象，字段包括：
- decision: pass 或 reject
- score: 1-100 整数
- strengths: 字符串数组
- defects: 字符串数组
- patch_summary: 字符串
- rerun_reason: 字符串
- decision_comment: 字符串
- rule_checks: 对象，至少包含 detail_density、relationship_pacing、villain_layering、system_boundary、scene_variety、public_payoff 六个布尔字段

判定标准：
1. 只要任一硬规则不满足，decision 必须是 reject。
2. 若出现以下任一点，直接 reject：
   - 细节不够，像梗概推进
   - 李梓沐关系推进过快
   - 李泽言或反派知道系统
   - 反派还是只有顾林赫单线压制
   - 与前一两集戏核重复
   - 没有真低谷或没有公开后果
3. 用户明确要求第4集是质量基线，控字数靠切集，不靠压扁写法。
4. 需要特别检查第{episode_no}集是否完成本集硬目标：{_episode_target_instruction(episode_no)}
5. 若本轮借用了素材结构，必须检查是否只是借了结构/节奏/公开反馈，而没有照搬具体剧情、角色名、台词或独有设定。
6. 必须检查是否违反前置设定层：角色目标漂移、关系越级、世界规则失效、金手指无代价乱开，都应直接判为缺陷。
7. 必须检查长线稳定：阶段目标有没有被写偏、前几集积累的冲突是否被跳过、是否为了赶进度牺牲关系与细节。
8. 必须检查观感稳定：动作密度、微反应、围观反馈、场面差异、尾钩差异不能比前几集明显变弱。

固定层记忆：
{fixed_memory or '- 暂无固定层记忆。'}

阶段层记忆：
{phase_memory or '- 暂无阶段层记忆。'}

单集层记忆：
{episode_memory or '- 暂无单集层记忆。'}

阶段复核重点：
{phase_review_focus}

前三集与前情摘要：
{previous_summary}

最近已通过集摘要：
{accepted_summary}

前置设定-世界观规则：
{story_bible_world_rules}

前置设定-关系护栏：
{story_bible_relationship_guardrails}

前置设定-金手指规则：
{story_bible_golden_finger_rules}

前置设定-冲突规划：
{story_bible_conflict_plan}

素材参考：
{material_reference}

风险护栏：
{material_risk_guardrails}

禁止照搬：
{material_do_not_copy}

本轮稿件标题：{rewrite_payload.get("title")}
本轮摘要：{rewrite_payload.get("summary")}
本轮正文：
{rewrite_payload.get("body")}

补充背景：
{((source_payload or {}).get("project_brief") or {}).get("outline") or (source_payload or {}).get("source_summary") or "无"}

当前轮次：第{attempt_no}轮。
'''


def _build_existing_episode_context(source_payload: dict[str, Any] | None) -> str:
    base_lines = [
        "第1集：厕所社死开局，顾林赫卡大考资格，系统绑定嘉豪，教室白板第一次公开翻盘。",
        "第2集：取消资格危机压上来，嘉豪在白板和心算上顶住，拿到重点观察组资格。",
        "第3集：论坛污蔑扩散，嘉豪公开反咬翻盘，李梓沐开始真正注意他，次日试炼楼集合。",
    ]
    source_summary = (source_payload or {}).get("source_summary")
    if source_summary:
        base_lines.append(f"原稿总纲：{source_summary}")
    return "\n".join(base_lines)


def _episode_target_instruction(episode_no: int) -> str:
    mapping = {
        5: "写第一次试炼楼实战小翻盘：垃圾堆里捡漏、顾林赫抢快搞砸、嘉豪靠观察修正拿到有效积分，并埋下更高位资料室钩子。",
        6: "写资格冻结型硬危机：不是简单扣分，而是下一轮资格被锁；嘉豪需要找到被动过手脚的证据，同时把父辈旧案线头露出来。",
        7: "写校花连坐：李梓沐因被迫与嘉豪绑定或同组承压，关系推进来自共担风险和舆论压力，不是突然暧昧。",
        8: "写5-10里最硬的一次真低谷之一：最好上升到班级/群体层面的代价或停赛，不要重复设备栽赃翻案。",
        9: "写更高位规则压制：顾林臻、何院长或父辈旧案把矛盾抬高，嘉豪要顶住更强制度打压。",
        10: "写阶段性开门：第5-9集积压的问题在第10集打开新门，但不能大结局，要留下更高阶世界或旧案继续推进的钩子。",
    }
    return mapping.get(episode_no, "保持主线升级。")


def _normalize_episode_script(content: str, episode_no: int) -> str:
    cleaned = _coerce_generation_text(content)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if cleaned.startswith(f"第{episode_no}集"):
        return cleaned
    return f"第{episode_no}集\n\n{cleaned}".strip()


def _build_episode_rewrite_fallback(source_payload: dict[str, Any] | None, error_message: str) -> list[dict[str, Any]]:
    fallback_titles = {
        5: "试炼楼捡漏",
        6: "资格被锁",
        7: "校花连坐",
        8: "全班停赛",
        9: "封机风暴",
        10: "旧案开门",
    }
    return [
        {
            "episode": episode_no,
            "title": fallback_titles[episode_no],
            "body": _fallback_episode_body(episode_no),
            "summary": f"第{episode_no}集动态重写失败，当前使用降级占位稿。错误：{error_message}",
            "attempts": 0,
            "passed": False,
            "score": 40,
            "strengths": [],
            "defects": ["动态链路失败，未完成正式重写"],
            "patch_summary": "需要恢复动态重写后重新执行",
            "rerun_reason": error_message,
            "decision_comment": "降级输出，仅供验收定位问题。",
            "rule_checks": {},
            "history": [],
        }
        for episode_no in range(CUSTOM_CAMPUS_REWRITE_EPISODE_START, CUSTOM_CAMPUS_REWRITE_EPISODE_END + 1)
    ]


def _fallback_episode_body(episode_no: int) -> str:
    return f"第{episode_no}集\n\n【场{episode_no}-1：待重写场景/日】\n人物：嘉豪、李泽言、李梓沐、顾林赫\n△ 动态重写失败，当前为占位稿。\nSYS: 当前集未生成成功，请恢复动态链后重跑。"


def _build_default_character_sheet(source_payload: dict[str, Any] | None) -> str:
    title = (source_payload or {}).get("title") or "重生为嘉豪：我靠装X迎娶软糯校花第一季"
    return "\n".join([
        f"- 项目：{title}",
        "- 陈嘉豪：穿越后的低位男主，黑历史满身，被全校当笑话，靠系统逼迫和前世认知差完成装X翻盘。",
        "- 系统：傲娇毒舌型系统，必须能说话、施压、怼人，并快速兑现奖励或惩罚。",
        "- 顾林赫：前期校园高位压制者，卡资格、带围观、持续羞辱嘉豪。",
        "- 李梓沐：软糯校花，不是工具人；先看见嘉豪的狼狈，再看见他的翻盘，对他产生注意和追问。",
        "- 李泽言：嘉豪当前唯一偏向他的同学，负责承接信息和陪衬围观反差。",
    ])


async def _generate_beat_sheet(generation_vars: dict[str, str]) -> dict[str, Any]:
    prompt = _render_step_prompt(
        "03_beat_sheet.md",
        {
            **generation_vars,
            "draft_episode": "1",
        },
    )
    return await _generate_step_json(prompt)


async def _generate_scene_list(generation_vars: dict[str, str], beat_sheet_result: dict[str, Any], draft_episode: int) -> dict[str, Any]:
    prompt = _render_step_prompt(
        "04_scene_list.md",
        {
            **generation_vars,
            "beat_sheet": beat_sheet_result.get("context_output") or beat_sheet_result.get("full_output", ""),
            "draft_episode": str(draft_episode),
        },
    )
    return await _generate_step_json(prompt)


async def _generate_script_draft(generation_vars: dict[str, str], scene_list_result: dict[str, Any], draft_episode: int) -> dict[str, Any]:
    prompt = _render_step_prompt(
        "05_script_draft.md",
        {
            **generation_vars,
            "scene_list": scene_list_result.get("context_output") or scene_list_result.get("full_output", ""),
            "draft_episode": str(draft_episode),
        },
    )
    system_prompt = _load_agent_prompt("executor-script-draft.md")
    return await _generate_step_json(prompt, system_prompt=system_prompt)


async def _generate_step_json(user_prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
    """使用 text_generation_v2 异步生成内容"""
    from app.config import config

    # 获取生成配置
    gen_config = getattr(config, 'text_generation', {}) or {}
    provider = gen_config.get('provider', 'openai')
    base_url = gen_config.get('base_url', 'https://api.openai.com')
    api_key = gen_config.get('api_key', '')
    model = gen_config.get('model', 'gpt-4')
    temperature = gen_config.get('temperature', 0.7)

    result = await generate_json(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=user_prompt,
        system_prompt=system_prompt or "你是短剧写作引擎。严格按要求输出 JSON 对象，不要输出解释。",
        temperature=temperature,
        max_tokens=4000,
    )

    content = result if isinstance(result, dict) else {}
    context_output = _coerce_generation_text(content.get("context_output"))
    full_output = _coerce_generation_text(content.get("full_output"))

    if not context_output or not full_output:
        # 如果返回格式不符合预期，使用整个 content 作为 full_output
        full_output = str(result) if not isinstance(result, dict) else json.dumps(result, ensure_ascii=False)
        context_output = full_output[:500]  # 取前500字符作为摘要

    return {
        "context_output": context_output,
        "full_output": full_output,
    }


def _coerce_generation_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2).strip()
    return ""


def _render_step_prompt(file_name: str, variables: dict[str, str]) -> str:
    template_text = (STEP_PROMPTS_DIR / file_name).read_text(encoding="utf-8")
    return Template(template_text).safe_substitute(variables)


def _load_agent_prompt(file_name: str) -> str:
    content = (AGENT_PROMPTS_DIR / file_name).read_text(encoding="utf-8")
    content = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
    return content.strip()


def _normalize_script_markdown(content: str, episode_no: int) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = re.sub(r"^##\s*第\s*%s\s*集[:：]?\s*剧本\s*\n*" % episode_no, "", cleaned)
    cleaned = re.sub(r"^###\s*场\s*(\d+)[:：]\s*", r"【场\1：", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^动作：\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^对白：\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^-\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("】\n人物：", "】\n人物：")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if cleaned.startswith("第"):
        return cleaned
    return f"第{episode_no}集\n\n{cleaned}".strip()


def _chapter_preview(title: str, content: str) -> str:
    preview = content.splitlines()[0] if content else ""
    return f"{title}：{preview}"


def _build_campus_season_plan(source_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    blocks = [
        {
            "start_episode": 1,
            "end_episode": 10,
            "arc_title": "厕所社死到第一次翻盘",
            "goal": "让嘉豪在卧龙凤雏学院最底层处境里先活下来，并用装X系统完成第一次公开翻面。",
            "hook": "李梓沐开始注意他，顾林赫把他列为重点打压对象。",
        },
        {
            "start_episode": 11,
            "end_episode": 20,
            "arc_title": "知识差碾压与资格争夺",
            "goal": "嘉豪靠前世知识差和系统任务连续打脸，拿到大考资格。",
            "hook": "顾林赫第一次被当众踩脸，校内风向开始倒转。",
        },
        {
            "start_episode": 21,
            "end_episode": 30,
            "arc_title": "队友成型与名场面升级",
            "goal": "李泽言和柳芷茗逐步进组，嘉豪把抽象装X翻成可复制的个人标签。",
            "hook": "全校开始模仿嘉豪名场面，但真正的系统任务门槛变高。",
        },
        {
            "start_episode": 31,
            "end_episode": 40,
            "arc_title": "顾林臻下场与师生压制",
            "goal": "顾林臻代表高阶强压系统下场，嘉豪必须在课堂、擂台和试炼里继续反杀。",
            "hook": "李梓沐公开站到嘉豪这边，反派开始上强度。",
        },
        {
            "start_episode": 41,
            "end_episode": 50,
            "arc_title": "觉醒前夜与最大社死任务",
            "goal": "系统抛出最羞耻也最致命的任务，逼嘉豪在全校围观下完成最大一次装X。",
            "hook": "成功就能摸到超规格武器，失败就彻底沦为笑柄。",
        },
        {
            "start_episode": 51,
            "end_episode": 60,
            "arc_title": "大考终局与八道口录取",
            "goal": "嘉豪完成武器觉醒、职业定位与终极打脸，带着核心队友冲进八道口技能学院。",
            "hook": "第一季结束时抛出更高阶世界与第二季打怪升级入口。",
        },
    ]
    return blocks


def _build_custom_campus_chapters(source_payload: dict[str, Any] | None, round_no: int) -> list[str]:
    chapter_1 = """第1集
1.1 学校厕所 日 内
人物：陈嘉豪、顾林赫、同学甲、同学乙
△ 地上有一滩脏水，隔间门半开。
△ 陈嘉豪蜷在地上，校服裤腿沾着鞋印，额头鼓着包，口罩歪到一边。
SFX: 哄笑声、抽水声混在一起。
同学甲：醒了醒了！你们猜这回他又说自己是谁？
同学乙：昨天夜店DJ，前天金融天才，今天又想装什么？
△ 陈嘉豪猛地睁眼，呼吸发急。
OS: 我不是在过马路吗？
△ 记忆碎片硬灌进脑海。黑皮、胖、矮、满脸痘，倒数第一，全天候被笑。
OS: 我穿成了全校的笑话？
△ 顾林赫鞋尖碾住陈嘉豪手边的耳机。
顾林赫：装晕装够没？要不要我再补一脚？
△ 周围又是一阵笑。
SYS: 叮。检测到宿主处于“公开社死现场”。
SYS: 绑定成功——抽象逆袭系统启动。
SYS: 新手任务一：三十分钟内摆脱“厕所废物”标签，制造第一次反向围观。
SYS: 失败惩罚：全校广播播放你原主昨晚甩头发的视频。
陈嘉豪：谁？
SYS: 你祖宗。少废话，先活。
△ 顾林赫抬脚踩住陈嘉豪胸口，俯身逼近。
顾林赫：今天午休你再敢碰教室白板，我让你连大考报名表都摸不到。
△ 陈嘉豪被踩得呼吸一滞，眼底一下冷了。
OS: 开局就卡大考资格？
陈嘉豪：你这么紧张干什么？
顾林赫：嗯？
陈嘉豪：怕我真翻身？
△ 顾林赫嗤笑，一脚把耳机踢进便池边的水里。
顾林赫：你先从地上爬起来再说。
△ 他转身就走。
同学甲：走走走，等会儿看废物回教室发癫。
△ 人散光后，陈嘉豪撑着地慢慢坐起，手心全是水和灰。
陈嘉豪：这开局也太烂了。
SYS: 你的优势就两个。
SYS: 第一，这世界的人文化水平低得感人。
SYS: 第二，原主够丢脸，你够不要脸。
SYS: 把社死翻成名场面，你就有第一口饭吃。
△ 陈嘉豪扶墙站起，看着镜子里那张惨不忍睹的脸。
OS: 行。烂到底了，就往上翻。
△ 他抹掉嘴角的血，扯正口罩，朝教室方向走。

1.2 高三七班门口 日 内
人物：陈嘉豪、李泽言
△ 李泽言守在门口，手里攥着半包纸巾，急得团团转。
李泽言：嘉豪！你没事吧？
陈嘉豪：死不了。
李泽言：顾林赫又堵你了？
△ 陈嘉豪看他一眼。
陈嘉豪：白板还能用吗？
李泽言：能是能……但你别吧？顾林赫刚放话了。
陈嘉豪：那就让他告。
李泽言：你又想干嘛？
陈嘉豪：翻盘。
△ 李泽言一愣。
李泽言：哥，你今天被打出新赛道了？
△ 陈嘉豪拍了拍他肩膀，推门进去。
OS: 既然他们都认定我是笑话，那我就先把笑话做大。

1.3 高三七班 日 内
人物：陈嘉豪、顾林赫、李梓沐、同学若干
△ 午休铃一响，希沃白板突然亮起炫彩音轨界面。
BGM: 土嗨电音猛地炸响。
△ 陈嘉豪一步跨上讲台，手指在屏幕上飞快划动，学着DJ搓盘。
△ 全班齐刷刷抬头。
同学甲：我靠，他真来了！
同学乙：厕所没挨够打是吧？
△ 陈嘉豪拿起粉笔，在黑板角落刷刷写下四个大字——全场最帅。
陈嘉豪：都醒醒！从今天开始，高三七班的课间审美，我接管。
△ 哄笑声瞬间炸开。
SYS: 围观情绪值+4。
SYS: 别停。笑话也是流量入口。
△ 顾林赫从后排站起来，脸色发沉。
顾林赫：陈嘉豪，你是不是厕所那顿还没吃够？
陈嘉豪：顾少，别急。热场完了再杀人。
△ 门口一静。李梓沐抱着医药箱站在那里，眉心微拧。
李梓沐：你额头都青了，还闹？
陈嘉豪：班花来了？那正好，看升级版。
顾林赫：梓沐，你别管他，他就喜欢哗众取宠。
△ 陈嘉豪突然关掉音乐。教室瞬间安静。
陈嘉豪：哗众取宠怎么了？能让你们都看我，就是本事。
△ 他转身在白板上写下“187+296=？”。
陈嘉豪：谁先算出来，谁接我下一首。
顾林赫：别装了，你连数学卷子名字都写不利索。
SYS: 检测到公开翻盘窗口。
SYS: 做题。打脸。敢算错你就死。
△ 陈嘉豪抬笔就写：483。
△ 全班安静一拍。数学课代表低头狂算，下一秒猛地抬头。
数学课代表：对了！
△ 李梓沐一怔。顾林赫笑意僵住。
陈嘉豪：这叫开胃菜。
SYS: 新手任务完成度70%。继续制造更大围观。
△ 教室外传来教导主任的脚步声。
SFX: 皮鞋声逼近。
SYS: 友情提醒，你下一波麻烦到了。
△ 陈嘉豪握着笔，缓缓看向门口，眼底反而亮了。
"""

    chapter_2 = """第2集
2.1 高三七班 日 内
人物：陈嘉豪、教导主任、何院长、顾林赫、李梓沐、全班同学
△ 教导主任推门而入，脸黑得能拧出水。何院长站在他身后，神色不明。
教导主任：陈嘉豪！你拿白板放歌、聚众起哄，还想不想参加大考！
△ 这句话一出，教室气氛瞬间一变。
OS: 来了。大考资格一没，我后面全废。
SYS: 临时任务二：在取消资格危机下维持“大佬错觉”三分钟。
SYS: 失败惩罚：全校循环播放你原主厕所甩头视频。
△ 白板角落，一个金融资讯小组件还亮着，红绿线乱跳。
△ 陈嘉豪眼神一动，突然切掉答题界面，把K线图放大。
△ 他双手背后，故意站出一副少年操盘手的架势。
教导主任：你又发什么疯？
陈嘉豪：主任，我不是胡闹。我在练动态信息处理。
教导主任：什么处理？
陈嘉豪：未来武器觉醒、职业分流、试炼判断，拼的就是脑子反应、数据预判、临场心算。
陈嘉豪：我只是把你们看不懂的东西，提前拿来练。
△ 他说完，拿起电子笔，在K线图旁边飞快列出几道加减混合算式。
△ 同学们想笑，却没人敢先开口。
顾林赫：你装什么股神？
陈嘉豪：你懂股吗？
顾林赫：……
陈嘉豪：不懂就闭嘴。
△ 周围爆出压不住的吸气声。
△ 李梓沐站在门边，眼神发怔。
何院长：刚才那题，是你自己算的？
陈嘉豪：是。
何院长：那这道呢？
△ 何院长亲手在白板上写下一串四位数加减混合题。
△ 全班轰动。
同学甲：这不是压轴难度吗？
SYS: 别怂。你前世好歹高考中上。
△ 陈嘉豪盯着题，脑子飞快运转，抬手写下答案。
△ 课代表、助教、旁边两个学生低头猛算。
课代表：对了！又对了！
△ 安静。死一样的安静。
△ 顾林赫脸上的笑彻底挂不住。李梓沐第一次像看陌生人一样看向陈嘉豪。
SYS: 临时任务完成。
SYS: 奖励知识+1。现在你强行装高深，更容易把外行唬住。
何院长：陈嘉豪，下周摸底考，你进重点观察组。
△ 教室轰然炸锅。
顾林赫：院长，这不公平！
何院长：公平？他答对了，你答了吗？
△ 顾林赫噎住。
何院长：卧龙凤雏学院不缺会起哄的人，缺的是能翻题的人。
△ 何院长转身离开，教导主任脸色虽难看，却没再提取消资格。
△ 陈嘉豪垂在身侧的手慢慢收紧，后背全是汗。
OS: 我赌对了。

2.2 教室后排 日 内
人物：陈嘉豪、顾林赫、李梓沐、李泽言
△ 院长一走，教室瞬间炸开。
李泽言：嘉豪！你真进重点观察组了！
陈嘉豪：低调。
顾林赫：你到底耍了什么把戏？
陈嘉豪：我说了，你不懂。
△ 他把白板界面重新切回股票图，手指轻轻敲了两下。
陈嘉豪：高手的世界，本来就很孤独。
"""

    chapter_3 = """第3集
3.1 操场看台 傍晚 外
人物：陈嘉豪、李梓沐、李泽言
△ 风从看台扫过去，广播里还在播晚自习通知。
△ 陈嘉豪坐在台阶上，手里转着一支笔，额角的伤还没消。
李梓沐：你今天为什么突然像变了个人？
陈嘉豪：有没有一种可能，我本来就很强，只是以前懒得展示？
李梓沐：你继续装。
△ 她嘴上嫌弃，却还是把消肿药丢进他怀里。
李梓沐：额头都这样了，还逞什么能。
陈嘉豪：你关心我？
李梓沐：我是怕你真被打残，连摸底考都进不了。
△ 陈嘉豪低头看着药，嘴角忍不住扬了一下。
SYS: 检测到女主好感波动。
SYS: 温馨提醒，你现在只是从“笑话”升级成“有点怪的人”。
△ 李泽言从远处狂奔过来，气喘吁吁。
李泽言：完了！顾林赫在论坛发帖，说你数学题提前偷看答案，还说白板上的股票界面是作弊工具！
△ 陈嘉豪眼神一沉。
OS: 来得倒快。

3.2 教学楼走廊 夜 内
人物：陈嘉豪、顾林赫、围观学生若干
△ 走廊尽头的电子屏亮着校内论坛热帖，围了一大圈人。
△ 标题高挂：陈嘉豪作弊装神，重点观察资格应取消。
同学甲：我就说嘛，他怎么可能突然会做题。
△ 顾林赫站在人群中间，双手插兜，神情得意。
顾林赫：我只是替大家问个公平。
△ 陈嘉豪慢慢走近，李泽言在后面急得冒汗。
李泽言：嘉豪，要不先找老师解释？
陈嘉豪：解释？
△ 他抬头扫了一眼电子屏，忽然笑了。
陈嘉豪：这么大阵仗，不利用一下都对不起你。
SYS: 临时任务三：在百人围观下完成一次公开反咬。
SYS: 失败惩罚：帖子置顶三天，你永远钉在“厕所股神”耻辱柱上。
顾林赫：来啊，解释。你不是很会算吗？
陈嘉豪：解释多没意思。咱们现场玩一把。
△ 他走到电子屏下方的互动白板前，抬手写下一行字：谁输谁公开道歉。
△ 围观人群瞬间炸了。
顾林赫：你拿什么跟我玩？
陈嘉豪：你出题，我当场答。
陈嘉豪：你要是输，就当着所有人承认，你怕我进重点观察组。
△ 顾林赫脸色一变。
顾林赫：你胡说八道什么？
陈嘉豪：不敢？
△ 围观声一下抬高。
围观众人：答应他！答应他！
△ 李梓沐从人群外挤进来，看向陈嘉豪的眼神彻底变了。
李梓沐：你确定？
陈嘉豪：今天不翻这个盘，我以后都得被他们踩着走。
△ 顾林赫被架上去，只能咬牙在白板上写题。
△ 陈嘉豪几乎没停，抬手就答，速度比昨天更快。
△ 围观学生现场验算，一阵接一阵惊呼。
同学乙：又对了！
△ 顾林赫握笔的手发僵，额角冒汗。
陈嘉豪：继续。
顾林赫：……
陈嘉豪：怎么，顾少的题库这么快就空了？
△ 哄笑声这回换了方向。
SYS: 围观翻面完成。
SYS: 反咬成功，体魄+1。
△ 李梓沐看着他，唇角轻轻翘了一下。
李梓沐：陈嘉豪。
陈嘉豪：嗯？
李梓沐：你还挺能演。
陈嘉豪：谢谢夸奖。我是实力派。
△ 人群还没散，远处广播突然响起紧急通知。
广播：请重点观察组学生，明早六点到试炼楼集合。逾期视为自动放弃资格。
△ 全场一静。
OS: 试炼楼？这节奏比我想的还快。
SYS: 恭喜你，真正的新手村要开了。
△ 陈嘉豪抬头看向漆黑的试炼楼方向，眼里的兴奋和紧张同时冒出来。
"""
    return [chapter_1, chapter_2, chapter_3]


def _build_full_three_chapters(benchmark: dict[str, Any]) -> list[str]:
    chapter_1 = "\n".join([
        "场景一｜医院走廊 夜 内",
        "△ 女主抱着离婚协议站在雨里，鞋跟断了一只。",
        "男主：你现在走，别后悔。",
        "女主：后悔的人不会是我。",
        "△ 电梯门打开，男主旧白月光挽着孩子走出来。",
        "OS: 她终于知道，自己这些年连正室都不算。",
        "△ 钩子：孩子喊了男主一声爸爸。",
    ])
    chapter_2 = "\n".join([
        "场景二｜地下车库 夜 内",
        "△ 女主拦车失败，被保安推开。",
        "闺蜜：你还想给他解释？",
        "女主：我不是解释，我是拿回属于我的东西。",
        "△ 她打开行李箱，里面全是替男主挡过的证据。",
        "△ 钩子：箱子最底层露出一张孩子的病危通知。",
    ])
    chapter_3 = "\n".join([
        "场景三｜董事会会议室 日 内",
        "△ 男主要宣布婚讯，女主带着审计报告闯入。",
        "女主：你可以订婚，但先把挪走的三千万解释清楚。",
        "△ 全场哗然，白月光手里的香槟杯砸碎。",
        "△ 钩子：女主当众点开监控，画面里男主母亲正在调包账本。",
    ])
    if benchmark["audience_axis"] == "male":
        chapter_1 = "\n".join([
            "场景一｜家族宴会厅 夜 内",
            "△ 男主坐在最角落，被未婚妻当众退婚。",
            "反派：废物就该认命。",
            "男主：你确定？",
            "△ 大屏突然切到集团股权变更书，第一继承人名字变成男主。",
            "△ 钩子：反派父亲当场站起，喊了男主一声少主。",
        ])
        chapter_2 = "\n".join([
            "场景二｜地下拳馆 夜 内",
            "△ 反派设局要废男主右手。",
            "男主：想赌？拿命来。",
            "△ 男主反手卸掉对方胳膊，全场站起。",
            "△ 钩子：拳馆老板递来一枚旧徽章，说这是你父亲留下的。",
        ])
        chapter_3 = "\n".join([
            "场景三｜董事局会议室 日 内",
            "△ 男主把一叠黑账砸到桌上。",
            "男主：今天不是来开会，是来清人。",
            "△ 三个叔伯脸色齐变，保镖同时封门。",
            "△ 钩子：主座背后的屏风后，真正的幕后老爷子鼓掌走出。",
        ])
    return [chapter_1, chapter_2, chapter_3]


def build_final_summary(track: str, best_sample: dict[str, Any], rounds: list[dict[str, Any]]) -> str:
    benchmark = get_track_benchmark(track)
    passed_round = next((item for item in rounds if item.get("passed")), rounds[-1] if rounds else {})
    rewrite_episodes = best_sample.get("rewrite_episodes") or []
    if rewrite_episodes:
        passed_count = sum(1 for item in rewrite_episodes if item.get("passed"))
        return (
            f"已完成{benchmark['big_category']} / {benchmark['sub_category']}赛道内部测试，并补跑第{CUSTOM_CAMPUS_REWRITE_EPISODE_START}-{CUSTOM_CAMPUS_REWRITE_EPISODE_END}集逐集重写；"
            f"重写通过{passed_count}/{len(rewrite_episodes)}集，最优样稿评分{best_sample.get('score', '未记录')}；"
            f"主要命中特征：{'、'.join(best_sample.get('accepted_features', [])[:4]) or '无'}；"
            f"最终状态：{'通过' if passed_round.get('passed') and passed_count == len(rewrite_episodes) else '待继续优化'}。"
        )
    return (
        f"已完成{benchmark['big_category']} / {benchmark['sub_category']}赛道内部测试，共运行{len(rounds)}轮；"
        f"最优样稿评分{best_sample.get('score', '未记录')}，"
        f"主要命中特征：{'、'.join(best_sample.get('accepted_features', [])[:3]) or '无'}；"
        f"最终状态：{'通过' if passed_round.get('passed') else '待继续优化'}。"
    )


def dumps_metadata(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ============================================================
# AI 生成统一入口（异步）
# ============================================================

import logging
logger = logging.getLogger(__name__)


async def generate_chapters_with_ai(
    track: str,
    round_no: int,
    use_ai: bool = True,
) -> dict[str, Any]:
    """使用AI生成剧本样稿（异步）。

    Args:
        track: 赛道名称，如 "女频情感 / 追妻火葬场"
        round_no: 当前轮次
        use_ai: 是否使用AI生成，False则回退到静态模板

    Returns:
        包含剧本内容的字典
    """
    if not use_ai:
        # 回退到静态模板
        return build_sample_payload(track, round_no)

    benchmark = get_track_benchmark(track)

    # 根据受众轴选择不同的生成策略
    if benchmark.get("audience_axis") == "male":
        system_prompt = _build_male_axis_system_prompt(benchmark)
        user_prompt = _build_male_axis_user_prompt(benchmark, round_no)
    else:
        system_prompt = _build_female_axis_system_prompt(benchmark)
        user_prompt = _build_female_axis_user_prompt(benchmark, round_no)

    try:
        from app.config import config

        gen_config = getattr(config, 'text_generation', {}) or {}

        result = await generate_json(
            provider=gen_config.get('provider', 'openai'),
            base_url=gen_config.get('base_url', 'https://api.openai.com'),
            api_key=gen_config.get('api_key', ''),
            model=gen_config.get('model', 'gpt-4'),
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.75,
            max_tokens=6000,
        )

        # 解析AI返回的结果
        payload = result if isinstance(result, dict) else {}
        chapters = payload.get("chapters") or payload.get("content", {}).get("chapters", [])

        if not chapters or len(chapters) < 3:
            # AI生成失败，回退到静态模板
            logger.warning(f"AI生成返回格式异常，回退到静态模板: {track} 第{round_no}轮")
            return build_sample_payload(track, round_no)

        chapter_titles = payload.get("chapter_titles", ["第1章", "第2章", "第3章"])
        sample_preview = "\n\n".join([
            _chapter_preview(f"第{i+1}章《{chapter_titles[i]}》", chapters[i])
            for i in range(min(3, len(chapters)))
        ])

        return {
            "title": payload.get("title") or f"{benchmark['sub_category']}·第{round_no}轮AI生成样稿",
            "track": track,
            "summary": payload.get("summary") or benchmark["script_summary"],
            "chapters": chapters[:3],
            "sample_preview": sample_preview,
            "chapter_titles": chapter_titles[:3],
            "accepted_features": payload.get("accepted_features") or benchmark.get("benchmark_features", [])[:4],
            "ip_core": benchmark.get("ip_core", []),
            "unit_strategy": benchmark.get("unit_strategy", ""),
            "hot_dimensions": benchmark.get("hot_dimensions", []),
            "sample_titles": benchmark.get("sample_titles", []),
            "generation_mode": "ai_generated",
            "rule_basis": "platform_benchmark",
            "ai_metadata": {
                "provider": gen_config.get('provider', 'openai'),
                "model": gen_config.get('model', 'gpt-4'),
                "temperature": 0.75,
            },
        }

    except Exception as exc:
        logger.error(f"AI生成失败: {exc}")
        # AI生成失败，回退到静态模板
        return build_sample_payload(track, round_no)


def _build_male_axis_system_prompt(benchmark: dict[str, Any]) -> str:
    """构建男频赛道的系统提示词"""
    return f"""你是专业的男频短剧编剧，擅长创作逆袭、打脸、装X类型的剧本。

赛道信息：
- 大类：{benchmark['big_category']}
- 子类：{benchmark['sub_category']}
- IP核心：{'、'.join(benchmark.get('ip_core', []))}
- 单元策略：{benchmark.get('unit_strategy', '')}

结构规则：
{chr(10).join('- ' + rule for rule in benchmark.get('structure_rules', []))}

表达规则：
{chr(10).join('- ' + rule for rule in benchmark.get('expression_rules', []))}

要求：
1. 只输出JSON格式，不要任何解释
2. 每章必须包含：场景标题、场景描述、对白、动作描述
3. 钩子要狠，每章结尾必须留悬念
4. 对白要短、狠、带网感

输出格式：
{{
  "title": "剧本标题",
  "summary": "一句话梗概",
  "chapters": ["第一章内容（场景格式）", "第二章内容", "第三章内容"],
  "chapter_titles": ["章节标题1", "章节标题2", "章节标题3"],
  "accepted_features": ["命中特征1", "命中特征2"]
}}"""


def _build_female_axis_system_prompt(benchmark: dict[str, Any]) -> str:
    """构建女频赛道的系统提示词"""
    return f"""你是专业的女频短剧编剧，擅长创作情感拉扯、追妻、虐恋类型的剧本。

赛道信息：
- 大类：{benchmark['big_category']}
- 子类：{benchmark['sub_category']}
- IP核心：{'、'.join(benchmark.get('ip_core', []))}
- 单元策略：{benchmark.get('unit_strategy', '')}

结构规则：
{chr(10).join('- ' + rule for rule in benchmark.get('structure_rules', []))}

表达规则：
{chr(10).join('- ' + rule for rule in benchmark.get('expression_rules', []))}

要求：
1. 只输出JSON格式，不要任何解释
2. 情感要有层次：入局→冲突→抽离→反噬/挽回
3. 对白要有情绪张力，但不长篇控诉
4. 每章结尾钩子要落在关系变化上

输出格式：
{{
  "title": "剧本标题",
  "summary": "一句话梗概",
  "chapters": ["第一章内容（场景格式）", "第二章内容", "第三章内容"],
  "chapter_titles": ["章节标题1", "章节标题2", "章节标题3"],
  "accepted_features": ["命中特征1", "命中特征2"]
}}"""


def _build_male_axis_user_prompt(benchmark: dict[str, Any], round_no: int) -> str:
    """构建男频赛道的用户提示词"""
    sample_titles = benchmark.get('sample_titles', [])
    hot_dimensions = benchmark.get('hot_dimensions', [])

    return f"""请为以下赛道创作前3章剧本（第{round_no}轮优化）：

赛道：{benchmark['big_category']} / {benchmark['sub_category']}
剧本概括：{benchmark['script_summary']}

参考标题（市场热门）：
{chr(10).join('- ' + t for t in sample_titles[:5])}

热门维度：
{chr(10).join('- ' + d for d in hot_dimensions[:5])}

要求：
1. 第1章：主角必须处于低位/被压制状态，出现公开羞辱场景
2. 第2章：主角开始反击/展现隐藏实力，要有围观群众反应
3. 第3章：打脸完成，但要留更大悬念/引出更强反派
4. 每章1500-2000字，标准剧本格式（场景头+动作+对白）
5. 对白要带网感，符合Z世代表达习惯"""


def _build_female_axis_user_prompt(benchmark: dict[str, Any], round_no: int) -> str:
    """构建女频赛道的用户提示词"""
    sample_titles = benchmark.get('sample_titles', [])
    hot_dimensions = benchmark.get('hot_dimensions', [])

    return f"""请为以下赛道创作前3章剧本（第{round_no}轮优化）：

赛道：{benchmark['big_category']} / {benchmark['sub_category']}
剧本概括：{benchmark['script_summary']}

参考标题（市场热门）：
{chr(10).join('- ' + t for t in sample_titles[:5])}

热门维度：
{chr(10).join('- ' + d for d in hot_dimensions[:5])}

要求：
1. 第1章：女主角受到伤害/误解/关系崩裂，出现明确痛点
2. 第2章：女主抽离/开始反击，男主后知后觉/开始后悔
3. 第3章：关系位置翻转，真相露头但代价显现
4. 每章1500-2000字，标准剧本格式（场景头+动作+对白）
5. 情绪要有递进，从隐忍到爆发"""
