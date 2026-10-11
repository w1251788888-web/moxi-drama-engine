import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _make_skill_session():
    from app.models.skill_registry import (
        SkillArtifact,
        SkillBinding,
        SkillInvocation,
        SkillQualityFeedback,
        SkillRegistry,
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        SkillRegistry.__table__,
        SkillBinding.__table__,
        SkillInvocation.__table__,
        SkillArtifact.__table__,
        SkillQualityFeedback.__table__,
    ):
        table.create(engine)
    return sessionmaker(bind=engine)()


def _write_manifest(tmp_path, skills):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"generated_by": "test", "skill_count": len(skills), "skills": skills}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _patch_manifest(monkeypatch, tmp_path, skills):
    from app.services import skill_workflow_service

    path = _write_manifest(tmp_path, skills)
    monkeypatch.setattr(skill_workflow_service, "MANIFEST_PATH", path)
    skill_workflow_service.load_skill_manifest.cache_clear()
    return skill_workflow_service


def test_skill_manifest_syncs_into_database_registry(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        },
        {
            "name": "superpowers-verification-before-completion",
            "source": "/skills/verification-before-completion",
            "target": "/integrated/verification-before-completion",
            "upstream_repo": "superpowers",
            "category": "quality",
            "recommended_for": ["完成前验证"],
            "why": "用于完成前核验。",
            "mode": "symlink",
        },
    ])
    db = _make_skill_session()
    try:
        result = service.sync_skill_manifest_to_db(db)
        catalog = service.get_db_skill_catalog(db)

        assert result["created_count"] == 2
        assert result["registry_count"] == 2
        assert [item["name"] for item in catalog] == [
            "superpowers-systematic-debugging",
            "superpowers-verification-before-completion",
        ]
        assert catalog[0]["source"] == "/skills/systematic-debugging"
        assert catalog[0]["recommended_for"] == ["根因分析"]
        assert catalog[0]["status"] == "active"
        assert catalog[0]["is_enabled"] is True
        assert catalog[0]["manifest_hash"]

        second = service.sync_skill_manifest_to_db(db)
        assert second["unchanged_count"] == 2
    finally:
        db.close()


def test_skill_recommendation_prefers_database_catalog(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        }
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        result = service.recommend_skill_workflow(
            failure_type="format_break",
            blocking_issues=["格式不符合场标规范"],
            context="script_scene",
            db=db,
        )

        assert result["catalog_source"] == "database"
        assert result["failure_type"] == "format_break"
        assert result["blocking_issue_count"] == 1
        assert any(item["name"] == "superpowers-systematic-debugging" for item in result["recommended_skills"])
        debugging_stage = next(stage for stage in result["stages"] if stage["stage"] == "debugging")
        assert debugging_stage["skills"][0]["source"] == "/skills/systematic-debugging"
    finally:
        db.close()


def test_skill_binding_adds_database_backed_recommendation(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        },
        {
            "name": "openspace-delegate-task",
            "source": "/skills/delegate-task",
            "target": "/integrated/delegate-task",
            "upstream_repo": "openspace",
            "category": "delegation",
            "recommended_for": ["复杂任务委派"],
            "why": "用于外部 worker 委派。",
            "mode": "symlink",
        },
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        binding = service.create_skill_binding(
            db,
            skill_name="openspace-delegate-task",
            binding_type="failure_type",
            binding_key="custom_failure",
            priority=5,
            config={"handoff": "worker"},
            metadata={"source": "unit-test"},
        )

        resolved = service.resolve_skill_bindings(db, failure_type="custom_failure")
        result = service.recommend_skill_workflow(failure_type="custom_failure", context="unit-test", db=db)

        assert resolved[0]["id"] == binding["id"]
        assert resolved[0]["config"] == {"handoff": "worker"}
        assert result["matched_bindings"][0]["skill_name"] == "openspace-delegate-task"
        assert any(
            item["name"] == "openspace-delegate-task" and item["binding"]["id"] == binding["id"]
            for item in result["recommended_skills"]
        )
    finally:
        db.close()


def test_skill_invocation_and_artifact_are_persisted(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        }
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        binding = service.create_skill_binding(
            db,
            skill_name="superpowers-systematic-debugging",
            binding_type="failure_type",
            binding_key="format_break",
            priority=10,
        )
        invocation = service.start_skill_invocation(
            db,
            skill_name="superpowers-systematic-debugging",
            binding_id=binding["id"],
            actor_type="admin",
            actor_id="unit-test",
            context="acceptance",
            failure_type="format_break",
            input_summary="复现格式错误",
            metadata={"trace": "case-1"},
        )
        finished = service.finish_skill_invocation(
            db,
            invocation["id"],
            status="success",
            output_summary="已定位根因",
            metadata={"trace": "case-1", "done": True},
        )
        artifact = service.create_skill_artifact(
            db,
            invocation_id=invocation["id"],
            artifact_type="markdown",
            title="排查记录",
            content="root cause",
            path="06-docs/debug.md",
        )
        feedback = service.create_skill_quality_feedback(
            db,
            invocation_id=invocation["id"],
            score=92,
            verdict="useful",
            reviewer_type="admin",
            reviewer_id="unit-test",
            notes="能复用",
        )

        invocations = service.list_skill_invocations(db, skill_name="superpowers-systematic-debugging")
        artifacts = service.list_skill_artifacts(db, invocation_id=invocation["id"])
        feedback_items = service.list_skill_quality_feedback(db, invocation_id=invocation["id"])

        assert finished["status"] == "success"
        assert finished["output_summary"] == "已定位根因"
        assert invocations[0]["id"] == invocation["id"]
        assert artifact["skill_name"] == "superpowers-systematic-debugging"
        assert artifacts[0]["title"] == "排查记录"
        assert feedback["score"] == 92
        assert feedback_items[0]["verdict"] == "useful"
    finally:
        db.close()


def test_skill_quality_feedback_summary_builds_priority_hints(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        },
        {
            "name": "openspace-delegate-task",
            "source": "/skills/delegate-task",
            "target": "/integrated/delegate-task",
            "upstream_repo": "openspace",
            "category": "delegation",
            "recommended_for": ["复杂任务委派"],
            "why": "用于外部 worker 委派。",
            "mode": "symlink",
        },
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        debug_1 = service.start_skill_invocation(
            db,
            skill_name="superpowers-systematic-debugging",
            actor_type="admin",
            actor_id="unit-test",
            context="quality-summary",
            failure_type="format_break",
            input_summary="格式错误复核",
        )
        debug_2 = service.start_skill_invocation(
            db,
            skill_name="superpowers-systematic-debugging",
            actor_type="admin",
            actor_id="unit-test",
            context="quality-summary",
            failure_type="format_break",
            input_summary="二次格式错误复核",
        )
        delegate = service.start_skill_invocation(
            db,
            skill_name="openspace-delegate-task",
            actor_type="admin",
            actor_id="unit-test",
            context="quality-summary",
            failure_type="state_drift",
            input_summary="状态漂移复核",
        )
        service.create_skill_quality_feedback(db, invocation_id=debug_1["id"], score=90, verdict="useful")
        service.create_skill_quality_feedback(db, invocation_id=debug_2["id"], score=94, verdict="useful")
        service.create_skill_quality_feedback(db, invocation_id=delegate["id"], score=20, verdict="blocked")

        summary = service.summarize_skill_quality_feedback(db, min_feedback=1)

        assert summary["source"] == "skill_quality_feedback"
        assert summary["total_feedback_count"] == 3
        assert summary["skill_count"] == 2
        assert summary["verdict_counts"]["useful"] == 2

        debug_item = next(item for item in summary["items"] if item["skill_name"] == "superpowers-systematic-debugging")
        assert debug_item["average_score"] == 92
        assert debug_item["failure_type_breakdown"][0] == {"failure_type": "format_break", "count": 2}
        assert debug_item["binding_priority_hint"]["action"] == "promote"
        assert debug_item["binding_priority_hint"]["suggested_priority_delta"] == -10

        delegate_item = next(item for item in summary["items"] if item["skill_name"] == "openspace-delegate-task")
        assert delegate_item["negative_rate"] == 1
        assert delegate_item["binding_priority_hint"]["action"] == "demote"
    finally:
        db.close()


def test_skill_workflow_worker_creates_auditable_plan(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        },
        {
            "name": "superpowers-verification-before-completion",
            "source": "/skills/verification-before-completion",
            "target": "/integrated/verification-before-completion",
            "upstream_repo": "superpowers",
            "category": "quality",
            "recommended_for": ["完成前验证"],
            "why": "用于完成前核验。",
            "mode": "symlink",
        },
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        result = service.run_skill_workflow_worker(
            db,
            failure_type="format_break",
            context="unit-worker",
            actor_type="system",
            max_skills=2,
        )

        assert result["worker"] == "skill_workflow_worker"
        assert result["planned_count"] == 2
        assert len(result["invocations"]) == 2
        assert len(result["artifacts"]) == 2
        assert result["artifacts"][0]["artifact_type"] == "workflow_plan"
        assert "执行计划" in result["artifacts"][0]["content"]
        assert service.list_skill_invocations(db, context="unit-worker")[0]["status"] == "success"
    finally:
        db.close()


def test_external_skill_runner_gate_requires_confirmation_and_redacts(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "openspace-delegate-task",
            "source": "/skills/delegate-task",
            "target": "/integrated/delegate-task",
            "upstream_repo": "OpenSpace",
            "category": "delegation",
            "recommended_for": ["复杂任务委派"],
            "why": "用于外部 worker 委派。",
            "mode": "symlink",
        }
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        binding = service.create_skill_binding(
            db,
            skill_name="openspace-delegate-task",
            binding_type="context",
            binding_key="external-runner",
            config={
                "external_runner": {
                    "enabled": True,
                    "allowed_parameters": ["task", "access_token"],
                    "param_schema": {
                        "task": {"type": "string", "required": True, "max_length": 200},
                        "access_token": {"type": "string", "max_length": 120},
                    },
                    "timeout_seconds": 20,
                    "max_timeout_seconds": 45,
                    "requires_confirmation": True,
                }
            },
        )

        try:
            service.prepare_external_skill_runner_request(
                db,
                skill_name="openspace-delegate-task",
                binding_id=binding["id"],
                parameters={"task": "检查短剧链路"},
            )
            raise AssertionError("external runner gate should require confirmation")
        except ValueError as exc:
            assert "人工确认" in str(exc)

        try:
            service.prepare_external_skill_runner_request(
                db,
                skill_name="openspace-delegate-task",
                binding_id=binding["id"],
                parameters={"task": "检查短剧链路", "shell": "rm -rf"},
                confirm_execution=True,
                confirmation_phrase=service.EXTERNAL_RUNNER_CONFIRMATION_PHRASE,
                confirmed_by="admin-1",
            )
            raise AssertionError("external runner gate should reject non-whitelisted parameters")
        except ValueError as exc:
            assert "白名单" in str(exc)

        result = service.prepare_external_skill_runner_request(
            db,
            skill_name="openspace-delegate-task",
            binding_id=binding["id"],
            parameters={"task": "检查短剧链路", "access_token": "secret-token"},
            context="unit-external",
            actor_id="admin-1",
            timeout_seconds=30,
            confirm_execution=True,
            confirmation_phrase=service.EXTERNAL_RUNNER_CONFIRMATION_PHRASE,
            confirmed_by="admin-1",
        )

        assert result["worker"] == "external_skill_runner_gate"
        assert result["status"] == "ready_for_external_runner"
        assert result["will_execute"] is False
        assert result["timeout_seconds"] == 30
        assert result["parameters"]["access_token"] == "[REDACTED]"
        assert result["invocation"]["status"] == "success"
        assert result["artifact"]["artifact_type"] == "external_runner_request"
        assert "secret-token" not in result["artifact"]["content"]
        assert "will_execute" in result["artifact"]["content"]
    finally:
        db.close()


def test_external_skill_runner_executor_runs_whitelisted_probe_once(monkeypatch, tmp_path):
    service = _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "openspace-delegate-task",
            "source": "/skills/delegate-task",
            "target": "/integrated/delegate-task",
            "upstream_repo": "OpenSpace",
            "category": "delegation",
            "recommended_for": ["复杂任务委派"],
            "why": "用于外部 worker 委派。",
            "mode": "symlink",
        }
    ])
    db = _make_skill_session()
    try:
        service.sync_skill_manifest_to_db(db)
        binding = service.create_skill_binding(
            db,
            skill_name="openspace-delegate-task",
            binding_type="context",
            binding_key="external-runner",
            config={
                "external_runner": {
                    "enabled": True,
                    "execution_enabled": True,
                    "allowed_runners": ["skill_echo_probe"],
                    "allowed_parameters": ["task", "access_token"],
                    "param_schema": {
                        "task": {"type": "string", "required": True, "max_length": 200},
                        "access_token": {"type": "string", "max_length": 120},
                    },
                    "timeout_seconds": 20,
                    "max_timeout_seconds": 45,
                    "requires_confirmation": True,
                }
            },
        )
        prepared = service.prepare_external_skill_runner_request(
            db,
            skill_name="openspace-delegate-task",
            binding_id=binding["id"],
            runner_name="skill_echo_probe",
            parameters={"task": "检查短剧链路", "access_token": "secret-token"},
            context="unit-external",
            actor_id="admin-1",
            timeout_seconds=30,
            confirm_execution=True,
            confirmation_phrase=service.EXTERNAL_RUNNER_CONFIRMATION_PHRASE,
            confirmed_by="admin-1",
        )

        try:
            service.execute_external_skill_runner_request(
                db,
                request_invocation_id=prepared["invocation"]["id"],
                confirm_execution=True,
                confirmation_phrase="WRONG",
                confirmed_by="admin-1",
            )
            raise AssertionError("executor should require the execution confirmation phrase")
        except ValueError as exc:
            assert "EXECUTE_EXTERNAL_SKILL_RUN" in str(exc)

        try:
            service.execute_external_skill_runner_request(
                db,
                request_invocation_id=prepared["invocation"]["id"],
                runner_name="unknown-runner",
                confirm_execution=True,
                confirmation_phrase=service.EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE,
                confirmed_by="admin-1",
            )
            raise AssertionError("executor should reject a runner that differs from prepare")
        except ValueError as exc:
            assert "准备阶段一致" in str(exc)

        result = service.execute_external_skill_runner_request(
            db,
            request_invocation_id=prepared["invocation"]["id"],
            confirm_execution=True,
            confirmation_phrase=service.EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE,
            confirmed_by="admin-1",
            actor_id="admin-1",
        )

        assert result["worker"] == "external_skill_runner_executor"
        assert result["will_execute"] is True
        assert result["status"] == "success"
        assert result["execution"]["returncode"] == 0
        assert result["execution"]["timed_out"] is False
        assert result["execution"]["command_key"] == "skill_echo_probe"
        assert result["invocation"]["failure_type"] == "external_skill_runner_execute"
        assert result["artifact"]["artifact_type"] == "external_runner_execution"
        assert "secret-token" not in result["artifact"]["content"]
        assert "access_token" in result["artifact"]["content"]
        assert "skill_echo_probe" in result["execution"]["stdout"]

        redacted_stdout, was_truncated = service._truncate_stdio("api_key=sk-live-secret token:abc123")
        assert was_truncated is False
        assert "sk-live-secret" not in redacted_stdout
        assert "abc123" not in redacted_stdout

        try:
            service.execute_external_skill_runner_request(
                db,
                request_invocation_id=prepared["invocation"]["id"],
                confirm_execution=True,
                confirmation_phrase=service.EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE,
                confirmed_by="admin-1",
            )
            raise AssertionError("executor should reject duplicate confirmation")
        except ValueError as exc:
            assert "已执行" in str(exc)
    finally:
        db.close()


def test_skill_workflow_router_uses_database_registry(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import verify_admin
    from app.database import get_db
    from app.main import app

    _patch_manifest(monkeypatch, tmp_path, [
        {
            "name": "superpowers-systematic-debugging",
            "source": "/skills/systematic-debugging",
            "target": "/integrated/systematic-debugging",
            "upstream_repo": "superpowers",
            "category": "debugging",
            "recommended_for": ["根因分析"],
            "why": "用于证据驱动排查。",
            "mode": "symlink",
        }
    ])
    db = _make_skill_session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        client = TestClient(app)

        sync = client.post("/api/admin/skill-workflows/sync")
        assert sync.status_code == 200, sync.text
        assert sync.json()["created_count"] == 1

        catalog = client.get("/api/admin/skill-workflows/catalog")
        assert catalog.status_code == 200, catalog.text
        payload = catalog.json()
        assert payload["source"] == "database"
        assert payload["skill_count"] == 1
        assert payload["skills"][0]["name"] == "superpowers-systematic-debugging"

        recommend = client.post(
            "/api/admin/skill-workflows/recommend",
            json={"failure_type": "format_break", "blocking_issues": ["格式错"], "context": "unit-test"},
        )
        assert recommend.status_code == 200, recommend.text
        assert recommend.json()["catalog_source"] == "database"

        binding = client.post(
            "/api/admin/skill-workflows/bindings",
            json={
                "skill_name": "superpowers-systematic-debugging",
                "binding_type": "failure_type",
                "binding_key": "format_break",
                "priority": 10,
                "config": {"route": "debug"},
            },
        )
        assert binding.status_code == 200, binding.text
        binding_id = binding.json()["id"]

        resolved = client.get("/api/admin/skill-workflows/bindings/resolve?failure_type=format_break")
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["items"][0]["id"] == binding_id

        invocation = client.post(
            "/api/admin/skill-workflows/invocations",
            json={
                "skill_name": "superpowers-systematic-debugging",
                "binding_id": binding_id,
                "context": "unit-test",
                "failure_type": "format_break",
                "input_summary": "router start",
            },
        )
        assert invocation.status_code == 200, invocation.text
        invocation_id = invocation.json()["id"]

        finished = client.put(
            f"/api/admin/skill-workflows/invocations/{invocation_id}/finish",
            json={"status": "success", "output_summary": "router done"},
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["status"] == "success"

        artifact = client.post(
            f"/api/admin/skill-workflows/invocations/{invocation_id}/artifacts",
            json={"artifact_type": "markdown", "title": "router artifact", "content": "ok"},
        )
        assert artifact.status_code == 200, artifact.text
        assert artifact.json()["invocation_id"] == invocation_id

        artifacts = client.get(f"/api/admin/skill-workflows/artifacts?invocation_id={invocation_id}")
        assert artifacts.status_code == 200, artifacts.text
        assert artifacts.json()["items"][0]["title"] == "router artifact"

        feedback = client.post(
            f"/api/admin/skill-workflows/invocations/{invocation_id}/feedback",
            json={"score": 88, "verdict": "useful", "notes": "router feedback"},
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["score"] == 88

        feedback_items = client.get(f"/api/admin/skill-workflows/quality-feedback?invocation_id={invocation_id}")
        assert feedback_items.status_code == 200, feedback_items.text
        assert feedback_items.json()["items"][0]["notes"] == "router feedback"

        feedback_summary = client.get("/api/admin/skill-workflows/quality-feedback/summary?min_feedback=1")
        assert feedback_summary.status_code == 200, feedback_summary.text
        assert feedback_summary.json()["total_feedback_count"] >= 1
        assert feedback_summary.json()["items"][0]["binding_priority_hint"]["action"] in {
            "promote",
            "review",
            "hold",
        }

        worker = client.post(
            "/api/admin/skill-workflows/worker/run",
            json={"failure_type": "format_break", "context": "router-worker", "max_skills": 1},
        )
        assert worker.status_code == 200, worker.text
        assert worker.json()["planned_count"] == 1
        assert worker.json()["artifacts"][0]["artifact_type"] == "workflow_plan"

        runner_binding = client.post(
            "/api/admin/skill-workflows/bindings",
            json={
                "skill_name": "superpowers-systematic-debugging",
                "binding_type": "context",
                "binding_key": "external-runner",
                "priority": 5,
                "config": {
                    "external_runner": {
                        "enabled": True,
                        "execution_enabled": True,
                        "allowed_runners": ["skill_echo_probe"],
                        "allowed_parameters": ["task", "api_key"],
                        "param_schema": {"task": {"type": "string", "required": True, "max_length": 200}},
                        "timeout_seconds": 15,
                        "max_timeout_seconds": 30,
                    }
                },
            },
        )
        assert runner_binding.status_code == 200, runner_binding.text

        denied_runner = client.post(
            "/api/admin/skill-workflows/runner/prepare",
            json={
                "skill_name": "superpowers-systematic-debugging",
                "binding_id": runner_binding.json()["id"],
                "runner_name": "skill_echo_probe",
                "parameters": {"task": "router gate"},
            },
        )
        assert denied_runner.status_code == 400

        prepared_runner = client.post(
            "/api/admin/skill-workflows/runner/prepare",
            json={
                "skill_name": "superpowers-systematic-debugging",
                "binding_id": runner_binding.json()["id"],
                "runner_name": "skill_echo_probe",
                "parameters": {"task": "router gate", "api_key": "sk-test"},
                "context": "router-external",
                "actor_id": "admin-router",
                "confirm_execution": True,
                "confirmation_phrase": "CONFIRM_EXTERNAL_SKILL_RUN",
                "confirmed_by": "admin-router",
            },
        )
        assert prepared_runner.status_code == 200, prepared_runner.text
        assert prepared_runner.json()["will_execute"] is False
        assert prepared_runner.json()["parameters"]["api_key"] == "[REDACTED]"
        assert prepared_runner.json()["artifact"]["artifact_type"] == "external_runner_request"

        denied_execute = client.post(
            "/api/admin/skill-workflows/runner/execute",
            json={
                "request_invocation_id": prepared_runner.json()["invocation"]["id"],
                "confirm_execution": True,
                "confirmation_phrase": "WRONG",
                "confirmed_by": "admin-router",
            },
        )
        assert denied_execute.status_code == 400

        executed_runner = client.post(
            "/api/admin/skill-workflows/runner/execute",
            json={
                "request_invocation_id": prepared_runner.json()["invocation"]["id"],
                "confirm_execution": True,
                "confirmation_phrase": "EXECUTE_EXTERNAL_SKILL_RUN",
                "confirmed_by": "admin-router",
                "actor_id": "admin-router",
            },
        )
        assert executed_runner.status_code == 200, executed_runner.text
        assert executed_runner.json()["will_execute"] is True
        assert executed_runner.json()["status"] == "success"
        assert executed_runner.json()["execution"]["command_key"] == "skill_echo_probe"
        assert executed_runner.json()["artifact"]["artifact_type"] == "external_runner_execution"

        duplicate_execute = client.post(
            "/api/admin/skill-workflows/runner/execute",
            json={
                "request_invocation_id": prepared_runner.json()["invocation"]["id"],
                "confirm_execution": True,
                "confirmation_phrase": "EXECUTE_EXTERNAL_SKILL_RUN",
                "confirmed_by": "admin-router",
            },
        )
        assert duplicate_execute.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(verify_admin, None)
        db.close()
