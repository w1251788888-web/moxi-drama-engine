"""剧集段落任务拆分服务

实现superpowers的2-5分钟任务拆分和gstack的阻塞式质量门
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from app.models.episode_segment import EpisodeSegment, SegmentReview, StepGate


class EpisodeSegmentService:
    """段落任务拆分服务"""

    # 段落定义：类型 -> (顺序, 默认字数, 描述)
    SEGMENT_DEFINITIONS = {
        "hook": {
            "sequence": 1,
            "target_words": 250,
            "description": "钩子段：开局吸引，建立可拍问题和未完成动作",
            "acceptance_criteria": [
                {"check": "字数", "min": 200, "max": 300, "weight": 0.2},
                {"check": "主角出现", "required": True, "weight": 0.3},
                {"check": "可拍未完成动作", "required": True, "weight": 0.5},
            ],
        },
        "validation": {
            "sequence": 2,
            "target_words": 300,
            "description": "验证段：主角回应，推进证据、关系或状态变化",
            "acceptance_criteria": [
                {"check": "字数", "min": 250, "max": 350, "weight": 0.2},
                {"check": "主角行动", "required": True, "weight": 0.4},
                {"check": "证据推进或状态变化", "required": True, "weight": 0.4},
            ],
        },
        "explosion": {
            "sequence": 3,
            "target_words": 350,
            "description": "爆发段：高潮冲突，情绪顶点",
            "acceptance_criteria": [
                {"check": "字数", "min": 300, "max": 400, "weight": 0.2},
                {"check": "冲突爆发", "required": True, "weight": 0.5},
                {"check": "情绪顶点", "required": True, "weight": 0.3},
            ],
        },
        "resolution": {
            "sequence": 4,
            "target_words": 300,
            "description": "收尾段：具体收束，停在未完成承诺",
            "acceptance_criteria": [
                {"check": "字数", "min": 250, "max": 350, "weight": 0.2},
                {"check": "本集收尾", "required": True, "weight": 0.4},
                {"check": "具体未完成承诺", "required": True, "weight": 0.4},
            ],
        },
    }

    def __init__(self, db: Session):
        self.db = db

    def initialize_episode_segments(self, session_id: str, episode_no: int) -> list[EpisodeSegment]:
        """初始化一集的所有段落

        当用户开始写某一集时，自动拆分为4个段落
        """
        segments = []

        for segment_type, config in self.SEGMENT_DEFINITIONS.items():
            # 检查是否已存在
            existing = (
                self.db.query(EpisodeSegment)
                .filter_by(session_id=session_id, episode_no=episode_no, segment_type=segment_type)
                .first()
            )

            if existing:
                segments.append(existing)
                continue

            segment = EpisodeSegment(
                session_id=session_id,
                episode_no=episode_no,
                segment_type=segment_type,
                sequence=config["sequence"],
                target_word_count=config["target_words"],
                status="pending",
                acceptance_criteria=json.dumps(config["acceptance_criteria"]),
            )
            self.db.add(segment)
            segments.append(segment)

        self.db.flush()

        # 按顺序排序
        segments.sort(key=lambda s: s.sequence)
        return segments

    def get_episode_segments(self, session_id: str, episode_no: int) -> list[EpisodeSegment]:
        """获取一集的所有段落"""
        segments = (
            self.db.query(EpisodeSegment)
            .filter_by(session_id=session_id, episode_no=episode_no)
            .order_by(EpisodeSegment.sequence.asc())
            .all()
        )

        if not segments:
            # 自动初始化
            segments = self.initialize_episode_segments(session_id, episode_no)

        return segments

    def get_segment(self, segment_id: str) -> Optional[EpisodeSegment]:
        """获取单个段落"""
        return self.db.query(EpisodeSegment).filter_by(id=segment_id).first()

    def generate_segment(
        self,
        segment_id: str,
        content: str,
        version_id: Optional[str] = None,
    ) -> EpisodeSegment:
        """生成段落内容（红-绿-重构循环中的"实现"阶段）"""
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"段落不存在: {segment_id}")

        # 更新内容
        segment.content = content
        segment.version_id = version_id
        segment.update_word_count()

        # 运行验证（测试阶段）
        validation = segment.validate()

        # 更新状态
        if validation["passed"]:
            segment.status = "green"  # 通过测试，进入绿状态
        else:
            segment.status = "red"  # 未通过，处于红状态

        self.db.flush()
        return segment

    def refactor_segment(
        self,
        segment_id: str,
        new_content: str,
        reason: str = "",
    ) -> EpisodeSegment:
        """重构段落（红-绿-重构循环中的"重构"阶段）"""
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"段落不存在: {segment_id}")

        if not segment.can_refactor():
            raise ValueError(f"已达到最大重构次数: {segment.max_refactors}")

        # 记录重构
        segment.refactor_count += 1
        segment.content = new_content
        segment.update_word_count()

        # 重新验证
        validation = segment.validate()

        if validation["passed"]:
            segment.status = "green"
        else:
            segment.status = "refactor"  # 需要再次重构

        self.db.flush()
        return segment

    def complete_segment(self, segment_id: str) -> EpisodeSegment:
        """完成段落（绿状态确认）"""
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"段落不存在: {segment_id}")

        if segment.status != "green":
            # 先验证
            validation = segment.validate()
            if not validation["passed"]:
                raise ValueError(f"段落未通过验证，不能完成: {validation}")

        segment.mark_complete()
        self.db.flush()
        return segment

    def get_segment_progress(self, session_id: str, episode_no: int) -> dict:
        """获取段落进度"""
        segments = self.get_episode_segments(session_id, episode_no)

        total = len(segments)
        completed = sum(1 for s in segments if s.status == "done")
        in_progress = sum(1 for s in segments if s.status in ["green", "red", "refactor"])

        # 检查是否可以进入下一段（阻塞式评审）
        can_proceed = True
        blocking_reason = ""

        for i, segment in enumerate(segments):
            if segment.status != "done":
                # 检查是否有阻塞性评审
                reviews = self.get_segment_reviews(segment.id)
                blocking_reviews = [r for r in reviews if r.is_blocking and r.verdict == "block"]

                if blocking_reviews:
                    can_proceed = False
                    blocking_reason = f"{segment.segment_type} 有阻塞性评审未解决"
                    break

                # 前面的段落必须完成
                if i > 0 and segments[i-1].status != "done":
                    can_proceed = False
                    blocking_reason = f"需先完成 {segments[i-1].segment_type}"
                    break

        return {
            "total_segments": total,
            "completed": completed,
            "in_progress": in_progress,
            "percent": int((completed / total) * 100) if total > 0 else 0,
            "can_proceed": can_proceed,
            "blocking_reason": blocking_reason,
            "segments": [s.to_dict() for s in segments],
        }

    # ─────────────────────────────────────────────────────────
    # 阻塞式评审
    # ─────────────────────────────────────────────────────────

    def create_segment_review(
        self,
        segment_id: str,
        session_id: str,
        verdict: Literal["pass", "block", "request_changes"],
        comments: str = "",
        issues: list[dict] = None,
        rewrite_suggestion: str = "",
        is_blocking: bool = True,
        reviewed_by: str = "ai",
        score: Optional[int] = None,
    ) -> SegmentReview:
        """创建段落实时评审"""
        review = SegmentReview(
            segment_id=segment_id,
            session_id=session_id,
            verdict=verdict,
            is_blocking=1 if is_blocking else 0,
            comments=comments,
            issues=json.dumps(issues or []),
            rewrite_suggestion=rewrite_suggestion,
            score=score,
            reviewed_by=reviewed_by,
        )
        self.db.add(review)

        # 更新段落的评审记录
        segment = self.get_segment(segment_id)
        if segment:
            review_ids = json.loads(segment.review_ids or "[]")
            review_ids.append(review.id)
            segment.review_ids = json.dumps(review_ids)

            # 如果是阻塞性block，更新段落状态
            if is_blocking and verdict == "block":
                segment.status = "refactor"

        self.db.flush()
        return review

    def get_segment_reviews(self, segment_id: str) -> list[SegmentReview]:
        """获取段落的评审记录"""
        return (
            self.db.query(SegmentReview)
            .filter_by(segment_id=segment_id)
            .order_by(SegmentReview.created_at.desc())
            .all()
        )

    def resolve_review(self, review_id: str) -> SegmentReview:
        """解决评审（取消阻塞状态）"""
        review = self.db.query(SegmentReview).filter_by(id=review_id).first()
        if not review:
            raise ValueError(f"评审不存在: {review_id}")

        review.is_blocking = 0
        self.db.flush()
        return review

    # ─────────────────────────────────────────────────────────
    # 步骤质量门（gstack式阻塞）
    # ─────────────────────────────────────────────────────────

    def get_or_create_step_gate(self, session_id: str, step_id: str) -> StepGate:
        """获取或创建步骤质量门"""
        gate = (
            self.db.query(StepGate)
            .filter_by(session_id=session_id, step_id=step_id)
            .first()
        )

        if gate:
            return gate

        # 创建新的质量门
        check_items = []
        if step_id == "script_draft":
            check_items = [
                {"item": "所有段落完成", "required": True},
                {"item": "总字数达标", "required": True},
                {"item": "平均评分达标", "required": True},
            ]

        gate = StepGate(
            session_id=session_id,
            step_id=step_id,
            status="open",
            min_score=0.7,
            check_items=json.dumps(check_items),
        )
        self.db.add(gate)
        self.db.flush()
        return gate

    def evaluate_step_gate(self, session_id: str, step_id: str) -> StepGate:
        """评估步骤质量门"""
        gate = self.get_or_create_step_gate(session_id, step_id)

        if step_id == "script_draft":
            # 计算所有段落的完成情况
            segments = (
                self.db.query(EpisodeSegment)
                .filter_by(session_id=session_id)
                .all()
            )

            if not segments:
                gate.actual_score = 0.0
                gate.check_results = json.dumps([])
                return gate

            # 检查项
            results = []

            # 1. 所有段落完成
            done_count = sum(1 for s in segments if s.status == "done")
            all_done = done_count == len(segments)
            results.append({
                "item": "所有段落完成",
                "passed": all_done,
                "detail": f"{done_count}/{len(segments)}",
            })

            # 2. 总字数达标
            total_words = sum(s.actual_word_count for s in segments)
            target_words = sum(s.target_word_count for s in segments)
            word_ratio = total_words / target_words if target_words > 0 else 0
            words_ok = 0.8 <= word_ratio <= 1.2
            results.append({
                "item": "总字数达标",
                "passed": words_ok,
                "detail": f"{total_words}/{target_words}",
            })

            # 3. 平均评分达标
            avg_score = sum(s.validation_score for s in segments) / len(segments)
            score_ok = avg_score >= gate.min_score
            results.append({
                "item": "平均评分达标",
                "passed": score_ok,
                "detail": f"{avg_score:.2f}/{gate.min_score}",
            })

            gate.actual_score = avg_score
            gate.check_results = json.dumps(results)

            # 自动判断是否可以通过
            can_pass, _ = gate.can_pass()
            if can_pass and gate.status == "open":
                # 不自动通过，等待人工确认
                pass

        self.db.flush()
        return gate

    def pass_step_gate(self, session_id: str, step_id: str, by: str = "user") -> StepGate:
        """通过步骤质量门（阻塞式）"""
        gate = self.evaluate_step_gate(session_id, step_id)
        gate.pass_gate(by)
        self.db.flush()
        return gate

    def can_proceed_to_next_step(self, session_id: str, current_step_id: str) -> tuple[bool, str]:
        """检查是否可以进入下一步（核心阻塞逻辑）"""
        gate = self.get_or_create_step_gate(session_id, current_step_id)

        can_pass, reason = gate.can_pass()
        if not can_pass:
            return False, f"步骤质量门未通过: {reason}"

        if gate.status not in ["passed", "bypassed"]:
            return False, "步骤质量门待审核，请先通过评审"

        return True, "可以进入下一步"

    # ─────────────────────────────────────────────────────────
    # 并行生成支持
    # ─────────────────────────────────────────────────────────

    def get_parallel_ready_segments(self, session_id: str) -> list[EpisodeSegment]:
        """获取可以并行生成的段落

        规则：
        1. 状态为pending或refactor的段落
        2. 前面的段落不能有阻塞性评审
        """
        all_segments = (
            self.db.query(EpisodeSegment)
            .filter_by(session_id=session_id)
            .order_by(EpisodeSegment.episode_no.asc(), EpisodeSegment.sequence.asc())
            .all()
        )

        ready = []
        episode_progress = {}  # episode_no -> 是否有前置阻塞

        for segment in all_segments:
            ep = segment.episode_no

            if ep not in episode_progress:
                episode_progress[ep] = {"has_blocking": False}

            # 如果前面有阻塞，这个段落不能并行
            if episode_progress[ep]["has_blocking"]:
                continue

            # 检查是否有阻塞性评审
            reviews = self.get_segment_reviews(segment.id)
            has_blocking = any(r.is_blocking and r.verdict == "block" for r in reviews)

            if has_blocking:
                episode_progress[ep]["has_blocking"] = True
                continue

            # 这个段落可以并行
            if segment.status in ["pending", "refactor", "red"]:
                ready.append(segment)

            # 如果完成了，下一个段落可以检查
            if segment.status == "done":
                continue
            else:
                # 未完成，后面的段落需要等
                episode_progress[ep]["has_blocking"] = True

        return ready

    def get_episode_assembly(self, session_id: str, episode_no: int) -> str:
        """组装完整的剧集内容"""
        segments = self.get_episode_segments(session_id, episode_no)

        parts = []
        for segment in segments:
            if segment.content:
                parts.append(f"\n## {self.SEGMENT_DEFINITIONS[segment.segment_type]['description']}\n")
                parts.append(segment.content)

        return "\n".join(parts)

    # ─────────────────────────────────────────────────────────
    # 修复19/22: 段落级 LLM 生成
    # ─────────────────────────────────────────────────────────

    SEGMENT_ROLE_DESC = {
        "hook": "段定位：开场段（前 7-15 秒）。承接上集集尾倒钩或本集节拍开场钩子；建立本集悬念；主角亮相；不要在此段揭露核心反转或写大爆点。",
        "validation": "段定位：验证段。主角对开场困境作出第一次实质性回应；对手或反派出招；第一回合小冲突；情绪逐步升温但**不要**在此段就写最终爆点。",
        "explosion": "段定位：爆发段。核心冲突在此段爆发；必须包含 ≥1 次反转 + ≥1 个爽感爆发点（标注谁看见了/围观性）；本集情绪顶点；不要写收尾。",
        "resolution": "段定位：收尾段。冲突收束（不一定全部解决，可以留代价）；**必须**在段尾写出本集集尾倒钩——具体到场所/角色/动作/未说完的话的可拍画面，不能写抽象悬念。",
    }

    @staticmethod
    def _validate_segment_strict(content: str, segment_type: str, target_words: int, previous_tail: str = "") -> dict:
        """段落级强校验：字数 + 段定位关键特征 + 承接迹象（修复24）"""
        import re as _re
        text = content or ""
        # 净字（不含标点空白）
        net = len("".join(ch for ch in text if not ch.isspace() and ch not in "，。！？、；：""''「」『』（）【】《》()[]{},.!?;:'\""))
        problems: list[str] = []
        # 字数
        mn = target_words - 50
        mx = target_words + 50
        if net < mn:
            problems.append(f"字数不足（{net}<{mn}）")
        elif net > mx:
            problems.append(f"字数超限（{net}>{mx}）")
        # 必须有 △ 或 角色：
        has_action = bool(_re.search(r'[△▲]', text))
        has_dialog = bool(_re.search(r'[^\s：:]{1,8}[（(]?[^：:\n]{0,12}[)）]?[：:].{2,}', text))
        if not has_action and not has_dialog:
            problems.append("缺少剧本元素（△ 动作或角色台词）")
        # JSON 漂移检测
        meta_count = len(_re.findall(r'["\']?(角色名清单|集末钩子|爽感爆发点列表|本集冲突链)["\']?\s*[:：]', text))
        if meta_count >= 2 and not has_action:
            problems.append("JSON 元数据漂移（应输出剧本正文）")
        # 段定位关键特征
        if segment_type == "resolution":
            # 必须有具体的定格画面或留下钩子
            has_specific_freeze = bool(_re.search(r'[△▲]|定格|画面|站在|拿着|看着|[^：:]{1,8}[：:]', text[-300:]))
            if not has_specific_freeze:
                problems.append("收尾段缺少具体定格画面")
        if segment_type == "explosion":
            # 必须有冲突描写（强动词）
            strong_verbs = ["摔", "拍", "砸", "吼", "冲", "扑", "拉", "推", "踢", "砍", "射", "刺", "撞", "扔", "甩", "跳", "夺"]
            if not any(v in text for v in strong_verbs):
                problems.append("爆发段缺少强冲突动作描写")
        # 承接迹象：上段尾部的关键词应在本段开头出现至少 1 个
        if previous_tail:
            tail_keywords = _re.findall(r'[一-鿿]{2,4}', previous_tail)[-15:]  # 取尾部最后若干 2-4 字词
            head_text = text[:200]
            hits = sum(1 for kw in tail_keywords if kw in head_text)
            if tail_keywords and hits == 0:
                problems.append("段间承接弱（本段开头未出现上段尾部任一关键词）")
        return {
            "passed": len(problems) == 0,
            "net_chars": net,
            "problems": problems,
        }

    def generate_segment_with_llm(
        self,
        segment_id: str,
        template_vars: dict,
        system_prompt: str,
        user_prompt_renderer,  # 调用方传入的渲染函数：(template_text, vars) -> str
        generate_text_fn,       # 调用方传入的 generate_text 函数：(sys, usr, **kw) -> str
        prompt_template: str,
        generation_kwargs: Optional[dict] = None,
        previous_segment_tail: str = "",
        n_candidates: int = 1,             # 修复25: 多候选生成
        accepted_segments_text: str = "",  # 修复25: 已通过段落参考（用于多样性筛选）
        max_retries: int = 1,              # 修复27: 失败重写次数
    ) -> EpisodeSegment:
        """用 LLM 生成段落内容并强校验（修复19/24/25/27）"""
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"段落不存在: {segment_id}")

        config = self.SEGMENT_DEFINITIONS.get(segment.segment_type)
        if not config:
            raise ValueError(f"未知段落类型: {segment.segment_type}")

        # 拼接段落专用模板变量
        seg_vars = dict(template_vars)
        seg_vars.update({
            "segment_type": segment.segment_type,
            "segment_type_zh": config["description"].split("：")[0],
            "segment_index": str(config["sequence"]),
            "target_words": str(config["target_words"]),
            "min_words": str(config["target_words"] - 50),
            "max_words": str(config["target_words"] + 50),
            "segment_role_description": self.SEGMENT_ROLE_DESC.get(segment.segment_type, ""),
            "previous_segment_tail": previous_segment_tail or "（首段，无上段尾部）",
        })
        user_prompt = user_prompt_renderer(prompt_template, seg_vars)
        kwargs = generation_kwargs or {}
        kwargs.setdefault("temperature", 0.7)
        kwargs.setdefault("max_tokens", 1000)

        target_words = config["target_words"]

        # 修复25/27：多候选 + 多轮重试，选最优
        best_content = ""
        best_score = -1.0
        best_problems: list[str] = ["未生成任何候选"]
        attempt_logs: list[dict] = []

        for attempt in range(max_retries + 1):
            # 失败重试时强化 prompt
            attempt_user_prompt = user_prompt
            if attempt > 0 and best_problems:
                attempt_user_prompt = user_prompt + (
                    "\n\n【上一稿存在以下硬问题，必须本轮修复】\n"
                    + "\n".join(f"- {p}" for p in best_problems)
                    + "\n请整段重写（不是补丁），把问题修掉同时保留剧本结构。"
                )

            for cand_i in range(max(1, n_candidates)):
                # 多候选用不同温度做轻微扰动
                cand_kwargs = dict(kwargs)
                if n_candidates > 1:
                    base_temp = float(kwargs.get("temperature", 0.7))
                    cand_kwargs["temperature"] = max(0.3, min(0.95, base_temp + (cand_i - n_candidates // 2) * 0.1))
                content = generate_text_fn(system_prompt, attempt_user_prompt, **cand_kwargs) or ""
                content = content.strip()
                if not content:
                    continue
                v = self._validate_segment_strict(content, segment.segment_type, target_words, previous_segment_tail)
                # 多样性分：用简易 jaccard（中文双字 ngram）vs accepted_segments_text 算重复度
                diversity = 1.0
                if accepted_segments_text:
                    diversity = 1.0 - _bigram_jaccard(content, accepted_segments_text)
                # 综合分：通过-基础分 + 多样性奖励 - 字数偏离扣分
                base = 1.0 if v["passed"] else 0.5 - 0.1 * len(v["problems"])
                score = base + 0.25 * diversity
                attempt_logs.append({
                    "attempt": attempt, "candidate": cand_i,
                    "passed": v["passed"], "net": v["net_chars"],
                    "diversity": round(diversity, 3), "score": round(score, 3),
                    "problems": v["problems"],
                })
                if score > best_score:
                    best_score = score
                    best_content = content
                    best_problems = v["problems"]

            # 如果本轮已找到通过的候选则提前终止
            if best_problems == [] or (best_problems and len(best_problems) == 0):
                break

        # 写回最终最优候选。全部候选为空时，保留原文，避免一次模型抖动清空用户正文。
        if best_content:
            segment.content = best_content
            segment.update_word_count()
            # 跑标准 validate 兼容旧 status 字段
            try:
                seg_validation = segment.validate()
                segment.status = "green" if seg_validation.get("passed") and not best_problems else "red"
            except Exception:
                segment.status = "green" if not best_problems else "red"
        else:
            segment.status = "red"
            best_problems = ["no_candidate_generated"]
        # 把强校验结果存到 validation_results
        import json as _json
        segment.validation_results = _json.dumps({
            "strict": {"passed": not best_problems, "problems": best_problems, "score": best_score},
            "attempts": attempt_logs,
        }, ensure_ascii=False)

        self.db.flush()
        return segment


def _bigram_jaccard(a: str, b: str) -> float:
    """简易中文双字 ngram Jaccard 相似度（修复25多样性筛选用）"""
    if not a or not b:
        return 0.0
    def grams(s: str) -> set[str]:
        chinese = "".join(ch for ch in s if "一" <= ch <= "鿿")
        return {chinese[i:i+2] for i in range(len(chinese) - 1)}
    ga = grams(a)
    gb = grams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0
