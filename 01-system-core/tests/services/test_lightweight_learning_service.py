"""
LightweightLearningService 单元测试

测试覆盖：
1. optimize_prompt - 三种模式的正确切换
2. record_generation - 自动记录生成结果
3. record_user_edit - 学习用户编辑
4. extract_success_patterns - 提取成功模式
5. generate_optimized_rules - 生成优化规则
6. get_evolution_status - 获取进化状态
"""
import os
import sys
import json
import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.lightweight_learning_service import (
    LightweightLearningService,
    LightweightOptimizationResult
)
from app.models.project_learning import (
    ProjectMaterial, UserEditRecord, WorkflowEfficiencyMetrics,
    MaterialStatus, MaterialType
)


class TestLightweightOptimizationResult:
    """测试优化结果数据类"""

    def test_dataclass_creation(self):
        """测试数据类正确创建"""
        result = LightweightOptimizationResult(
            final_prompt="最终提示词",
            user_prompt="用户提示词",
            prefix="前缀",
            suffix="后缀",
            stats={"count": 5},
            mode="transparent"
        )
        assert result.final_prompt == "最终提示词"
        assert result.user_prompt == "用户提示词"
        assert result.mode == "transparent"


class TestOptimizePrompt:
    """测试提示词优化功能 - 核心方法"""

    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库会话"""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_db):
        """创建服务实例"""
        return LightweightLearningService(mock_db)

    def test_transparent_mode_new_project(self, service, mock_db):
        """测试新项目使用透明模式 - 不改变用户提示词"""
        # 模拟没有历史数据
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.optimize_prompt(
            project_id="new_project",
            user_prompt="请写一个钩子段",
            segment_type="hook",
            episode_no=1
        )

        assert result.mode == "transparent"
        assert result.final_prompt == "请写一个钩子段"
        assert result.user_prompt == "请写一个钩子段"
        assert result.prefix == ""
        assert result.suffix == ""

    def test_transparent_mode_with_threshold_override(self, service, mock_db):
        """测试透明模式阈值可配置"""
        with patch.dict(os.environ, {'LEARNING_TRANSPARENT_THRESHOLD': '5'}):
            # 重新创建服务以读取新环境变量
            service = LightweightLearningService(mock_db)
            mock_db.query.return_value.filter.return_value.count.return_value = 3

            result = service.optimize_prompt(
                project_id="project",
                user_prompt="测试",
                segment_type="hook",
                episode_no=1
            )

            # 3 < 5，应该还是透明模式
            assert result.mode == "transparent"

    def test_lightweight_mode_with_history(self, service, mock_db):
        """测试有足够历史时进入轻量模式"""
        # 模拟有5个历史素材
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        # 模拟有同类素材
        mock_material = MagicMock()
        mock_material.content = "测试内容"
        mock_material.context = json.dumps({"word_count": 250})
        mock_material.quality_score = 0.8

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_material] * 3

        result = service.optimize_prompt(
            project_id="project_with_history",
            user_prompt="请写一个钩子段",
            segment_type="hook",
            episode_no=5
        )

        # 5 >= TRANSPARENT_THRESHOLD(3) 且 < LIGHTWEIGHT_THRESHOLD(10)
        assert result.mode == "lightweight"
        assert "用户定义" in result.prefix  # 检查前缀包含用户规则标记
        assert result.user_prompt == "请写一个钩子段"  # 用户提示词100%保留
        assert result.final_prompt.startswith(result.prefix)

    def test_lightweight_mode_insufficient_data_fallback(self, service, mock_db):
        """测试轻量模式数据不足时回退到透明模式"""
        mock_db.query.return_value.filter.return_value.count.return_value = 5
        # 同类素材不足
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = service.optimize_prompt(
            project_id="project",
            user_prompt="测试",
            segment_type="hook",
            episode_no=1
        )

        # 应该回退到透明模式
        assert result.mode == "transparent"

    def test_smart_mode_with_short_input(self, service, mock_db):
        """测试短输入触发智能补全模式"""
        mock_db.query.return_value.filter.return_value.count.side_effect = [15, 5]

        # 模拟有历史素材
        mock_material = MagicMock()
        mock_material.content = "测试内容"
        mock_material.context = json.dumps({"word_count": 250})
        mock_material.quality_score = 0.85

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_material] * 5
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        # 短输入（少于50字）
        result = service.optimize_prompt(
            project_id="mature_project",
            user_prompt="写钩子",  # 只有3个字
            segment_type="hook",
            episode_no=10
        )

        assert result.mode == "smart"
        assert "用户常用规则模板" in result.prefix
        assert result.suffix != ""  # 有后缀提醒

    def test_smart_mode_with_long_input_fallback(self, service, mock_db):
        """测试长输入在智能阶段回退到轻量模式"""
        mock_db.query.return_value.filter.return_value.count.return_value = 15

        mock_material = MagicMock()
        mock_material.content = "测试"
        mock_material.context = json.dumps({"word_count": 200})
        mock_material.quality_score = 0.8

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_material] * 5

        # 长输入（超过50字）
        long_prompt = "请写一个精彩的钩子段落，要求有强烈冲突，主角装逼打脸反派，字数控制在250字左右，并加入明确的情绪递进、人物反应和结尾反转。"
        result = service.optimize_prompt(
            project_id="mature_project",
            user_prompt=long_prompt,
            segment_type="hook",
            episode_no=10
        )

        # 长输入应该回退到轻量模式
        assert result.mode == "lightweight"


class TestRecordGeneration:
    """测试生成结果记录功能 - AUTO-CAPTURE"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_record_generation_basic(self, service):
        """测试基本记录功能"""
        svc, mock_db = service

        svc.record_generation(
            project_id="test_project",
            segment_type="hook",
            episode_no=1,
            content="这是一个测试段落，包含冲突和转折。",
            validation_score=0.85
        )

        # 验证添加了素材
        assert mock_db.add.call_count >= 1
        assert mock_db.commit.called

        # 验证调用参数
        call_args = mock_db.add.call_args_list[0][0][0]
        assert call_args.project_id == "test_project"
        assert call_args.quality_score == 0.85
        assert call_args.status == MaterialStatus.AUTO_RECORDED.value

    def test_record_generation_word_count_extraction(self, service):
        """测试字数统计"""
        svc, mock_db = service

        content = "这是一个测试内容，用于验证字数统计功能。"
        svc.record_generation(
            project_id="test",
            segment_type="validation",
            episode_no=2,
            content=content,
            validation_score=None  # 测试默认值
        )

        call_args = mock_db.add.call_args_list[0][0][0]
        context = json.loads(call_args.context)
        assert context["word_count"] == len(content)
        assert context["episode_no"] == 2

    def test_record_generation_conflict_detection(self, service):
        """测试冲突关键词检测"""
        svc, mock_db = service

        content_with_conflict = "两人发生激烈冲突，互相争吵对抗。"
        svc.record_generation(
            project_id="test",
            segment_type="explosion",
            episode_no=3,
            content=content_with_conflict,
            validation_score=0.9
        )

        call_args = mock_db.add.call_args_list[0][0][0]
        context = json.loads(call_args.context)
        assert context["conflict_count"] >= 3  # 冲突、争吵、对抗


class TestRecordUserEdit:
    """测试用户编辑学习功能"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_record_valid_edit(self, service):
        """测试记录有效编辑"""
        svc, mock_db = service

        before = "这是修改前的内容，比较短。"
        after = "这是修改后的内容，经过用户精心编辑，增加了更多细节和描写，使情节更加丰富完整。"

        svc.record_user_edit(
            project_id="test",
            segment_type="hook",
            before_content=before,
            after_content=after
        )

        # 验证编辑记录和候选素材都被添加
        assert mock_db.add.call_count >= 2
        assert mock_db.commit.called

    def test_skip_minor_deletion(self, service):
        """测试跳过大段删除（可能不是改进）"""
        svc, mock_db = service

        before = "这是一段很长的内容，包含很多细节和情节发展。"
        after = "短。"  # 删除太多

        svc.record_user_edit(
            project_id="test",
            segment_type="hook",
            before_content=before,
            after_content=after
        )

        # 不应该添加任何记录
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_user_edit_creates_candidate_material_needing_human_review(self, service):
        """用户编辑只能沉淀为候选证据，不能自动批准为高质量素材"""
        svc, mock_db = service

        before = "原始内容"
        after = "用户改进后的高质量内容，字数足够长才能被记录。" * 3

        svc.record_user_edit(
            project_id="test",
            segment_type="resolution",
            before_content=before,
            after_content=after
        )

        # 找到素材记录
        material_calls = [call for call in mock_db.add.call_args_list
                         if isinstance(call[0][0], ProjectMaterial)]

        # 验证只创建候选素材，不能自动 approved。
        assert len(material_calls) > 0
        material = material_calls[0][0][0]
        assert material.status == MaterialStatus.CANDIDATE.value
        assert material.quality_score == 0.0
        assert material.user_rating == 0
        assert "needs_human_review" in material.tags
        assert "user_edit_candidate_only_not_auto_approved" in material.context

    def test_manual_edit_evidence_creates_candidate_scene_material(self, service):
        """保存正文带候选快照时，只进入候选证据池，不自动升级规则"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.first.return_value = None

        material_id = svc.record_manual_edit_evidence(
            project_id="test",
            episode_no=2,
            scene_no=1,
            saved_content="用户最终保存稿，承接旧账线索并改强了结尾钩子。",
            evidence={
                "model_candidate_snapshot": {
                    "content": "AI候选稿",
                    "content_hash": "candidate-hash",
                },
                "saved_content_hash": "saved-hash",
                "manual_edit_delta": {
                    "previous_candidate_hash": "candidate-hash",
                    "current_content_hash": "saved-hash",
                },
            },
            commit=False,
        )

        assert material_id
        material_calls = [
            call for call in mock_db.add.call_args_list
            if isinstance(call[0][0], ProjectMaterial)
        ]
        assert material_calls
        material = material_calls[0][0][0]
        assert material.status == MaterialStatus.CANDIDATE.value
        assert material.quality_score == 0.0
        assert material.user_rating == 0
        assert "candidate_evidence" in material.tags
        assert "needs_human_review" in material.tags
        assert "user_edit_candidate_only_not_auto_approved" in material.context


class TestExtractSuccessPatterns:
    """测试成功模式提取 - AUTO-IMPROVE"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_insufficient_materials_returns_empty(self, service):
        """测试素材不足时返回空列表"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.all.return_value = []

        patterns = svc.extract_success_patterns("project")

        assert patterns == []

    def test_extract_patterns_with_high_quality_materials(self, service):
        """测试从高质量素材中提取模式"""
        svc, mock_db = service

        # 创建模拟素材
        mock_materials = []
        for i in range(5):
            m = MagicMock()
            m.material_type = "OBSERVED_HOOK"
            m.content = f"高质量钩子段内容{i}"
            m.context = json.dumps({
                "word_count": 250 + i * 10,
                "conflict_count": 2
            })
            m.quality_score = 0.85
            mock_materials.append(m)

        mock_db.query.return_value.filter.return_value.all.return_value = mock_materials

        patterns = svc.extract_success_patterns("project")

        assert len(patterns) > 0
        # 检查模式结构
        pattern = patterns[0]
        assert 'segment_type' in pattern
        assert 'sample_count' in pattern
        assert 'avg_word_count' in pattern
        assert 'confidence' in pattern

    def test_pattern_confidence_calculation(self, service):
        """测试置信度计算"""
        svc, mock_db = service

        mock_materials = []
        for i in range(5):
            m = MagicMock()
            m.material_type = "OBSERVED_VALIDATION"
            m.content = f"内容{i}"
            m.context = json.dumps({"word_count": 200})
            m.quality_score = 0.8
            mock_materials.append(m)

        mock_db.query.return_value.filter.return_value.all.return_value = mock_materials

        patterns = svc.extract_success_patterns("project")

        if patterns:
            # 5个样本，置信度应该是 5/10 = 0.5
            assert patterns[0]['confidence'] == 0.5


class TestGenerateOptimizedRules:
    """测试生成优化规则"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_no_patterns_returns_none(self, service):
        """测试无模式时返回None"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.all.return_value = []

        rules = svc.generate_optimized_rules("project")

        assert rules is None

    def test_generate_rules_with_patterns(self, service):
        """测试有模式时生成规则"""
        svc, mock_db = service

        # 模拟素材
        mock_materials = []
        for segment_type in ['hook', 'validation', 'explosion']:
            for i in range(3):
                m = MagicMock()
                m.material_type = f"OBSERVED_{segment_type.upper()}"
                m.content = f"{segment_type}内容{i}"
                m.context = json.dumps({
                    "word_count": 200 + i * 20,
                    "conflict_count": i
                })
                m.quality_score = 0.82
                mock_materials.append(m)

        mock_db.query.return_value.filter.return_value.all.return_value = mock_materials

        rules = svc.generate_optimized_rules("project")

        assert rules is not None
        assert "基于项目成功案例自动生成的优化规则" in rules
        # 检查是否包含各段落类型的规则
        assert "HOOK 段优化规则" in rules or "hook" in rules.lower()


class TestGetEvolutionStatus:
    """测试获取进化状态"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_observing_stage(self, service):
        """测试观察期状态"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.count.return_value = 2

        status = svc.get_evolution_status("project")

        assert status['learning_stage'] == 'observing'
        assert status['total_samples'] == 2
        assert status['input_savings_percent'] == 0.0

    def test_learning_stage(self, service):
        """测试学习期状态"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        status = svc.get_evolution_status("project")

        assert status['learning_stage'] == 'learning'
        assert status['input_savings_percent'] == 0.15

    def test_mature_stage(self, service):
        """测试成熟期状态"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.count.return_value = 25

        # 模拟有模式
        with patch.object(svc, 'extract_success_patterns', return_value=[{}, {}]):
            status = svc.get_evolution_status("project")

        assert status['learning_stage'] == 'mature'

    def test_next_milestone_calculation(self, service):
        """测试下一个里程碑计算"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        status = svc.get_evolution_status("project")

        assert 'next_milestone' in status
        # 5个样本，下一个里程碑是10（轻量模式解锁）
        assert status['next_milestone']['samples_needed'] == 5


class TestEnvironmentConfiguration:
    """测试环境变量配置"""

    def test_default_thresholds(self):
        """测试默认阈值"""
        mock_db = MagicMock()
        service = LightweightLearningService(mock_db)

        assert service.TRANSPARENT_THRESHOLD == 3
        assert service.LIGHTWEIGHT_THRESHOLD == 10
        assert service.QUALITY_THRESHOLD_HIGH == 0.8
        assert service.SMART_MODE_INPUT_THRESHOLD == 50

    def test_custom_thresholds_from_env(self):
        """测试从环境变量读取阈值"""
        env_vars = {
            'LEARNING_TRANSPARENT_THRESHOLD': '5',
            'LEARNING_LIGHTWEIGHT_THRESHOLD': '15',
            'LEARNING_QUALITY_THRESHOLD_HIGH': '0.85',
            'LEARNING_SMART_INPUT_THRESHOLD': '100'
        }

        with patch.dict(os.environ, env_vars):
            mock_db = MagicMock()
            service = LightweightLearningService(mock_db)

            assert service.TRANSPARENT_THRESHOLD == 5
            assert service.LIGHTWEIGHT_THRESHOLD == 15
            assert service.QUALITY_THRESHOLD_HIGH == 0.85
            assert service.SMART_MODE_INPUT_THRESHOLD == 100


class TestEdgeCases:
    """测试边界情况"""

    @pytest.fixture
    def service(self):
        mock_db = MagicMock()
        return LightweightLearningService(mock_db), mock_db

    def test_json_decode_error_handling(self, service):
        """测试JSON解析错误处理"""
        svc, mock_db = service

        # 创建有无效context的素材
        mock_material = MagicMock()
        mock_material.content = "测试"
        mock_material.context = "invalid json"
        mock_material.quality_score = 0.8

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_material]

        # 不应该抛出异常
        stats = svc._get_segment_stats("project", "hook")
        assert stats is not None
        assert stats['count'] == 1

    def test_empty_user_prompt(self, service):
        """测试空用户提示词"""
        svc, mock_db = service
        mock_db.query.return_value.filter.return_value.count.return_value = 15
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = svc.optimize_prompt(
            project_id="project",
            user_prompt="",  # 空提示词
            segment_type="hook",
            episode_no=1
        )

        # 空提示词应该触发智能补全
        assert result.mode == "smart"

    def test_unicode_content_handling(self, service):
        """测试Unicode内容处理"""
        svc, mock_db = service

        unicode_content = "测试Unicode：🎭 剧情冲突！「台词」"
        svc.record_generation(
            project_id="test",
            segment_type="hook",
            episode_no=1,
            content=unicode_content,
            validation_score=0.9
        )

        # 验证正常处理
        assert mock_db.add.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
