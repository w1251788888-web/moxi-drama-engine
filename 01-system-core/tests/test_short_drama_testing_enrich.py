import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene
from app.schemas.short_drama_writing import TestingScriptRequest
from app.services.short_drama_testing_enrich import enrich_testing_request_from_project


def test_enrich_request_uses_previous_locked_official_source_as_nplus1_canon(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'testing-enrich.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    ProjectV2.__table__.create(bind=engine)
    Episode.__table__.create(bind=engine)
    Scene.__table__.create(bind=engine)
    ContentVersion.__table__.create(bind=engine)
    EvidenceEvent.__table__.create(bind=engine)

    saved_tail = "△林若岚、林承岳、许景深，三人目光同时钉在那个屏幕上。三种表情，三种没说完的话。"
    saved_content = "\n".join([
        "【场9-1：日 外 社区公告台】",
        "林若岚：今天只说账。",
        saved_tail,
    ])
    locked_file = tmp_path / "locked-episode-9.md"
    locked_file.write_text(saved_content, encoding="utf-8")
    saved_hash = hashlib.sha256(saved_content.encode("utf-8")).hexdigest()

    with Session() as db:
        db.add(ProjectV2(
            id="project-nplus1",
            name="N+1 正史测试",
            project_type="真人短剧",
            audience_axis="混合",
            genre_main="其他",
            genre_sub="逆袭",
            config="{}",
            workspace_path=str(tmp_path),
        ))
        db.add(Episode(
            id="episode-9",
            project_id="project-nplus1",
            episode_number=9,
            title="公开说明会",
            summary="林若岚在社区公告台公开证据。",
            status="completed",
        ))
        db.add(Scene(
            id="scene-9-1",
            episode_id="episode-9",
            scene_number=1,
            status="completed",
            content="ordinary scene content must not become source",
            word_count=len(saved_content),
        ))
        version = ContentVersion(
            id="locked-version-ep9",
            project_id="project-nplus1",
            episode_number=9,
            scene_number=0,
            version_code="v001",
            content_path=str(locked_file),
            content_hash=saved_hash,
        )
        db.add(version)
        db.add(EvidenceEvent(
            project_id="project-nplus1",
            event_type="episode_locked",
            target_type="episode",
            target_id="9",
            content_version_id=version.id,
            content_hash=version.content_hash,
        ))
        db.commit()

        req = TestingScriptRequest(
            project_id="project-nplus1",
            episode_no=10,
            episode_summary="第10集必须承接第9集公开说明会尾钩。",
            materials=[{"title": "占位素材"}],
            issue_feedback={"scope": "skip_material_lookup"},
            previous_episode_briefs=[
                {"episode_no": 9, "title": "公开说明会", "summary": "前端缓存摘要", "actual_progress": ""}
            ],
            episode_memory_cards=[
                {"episode_no": 4, "ending_state": "旧缓存尾巴，不应成为第10集上一尾。"}
            ],
        )

        enriched = enrich_testing_request_from_project(req, db)

    ep9_brief = next(item for item in enriched.previous_episode_briefs if item["episode_no"] == 9)
    ep9_card = next(item for item in enriched.episode_memory_cards if item["episode_no"] == 9)

    assert saved_tail in ep9_brief["actual_progress"]
    assert saved_tail in ep9_brief["body_excerpt"]
    assert ep9_brief["ending_state"] == saved_tail
    assert saved_tail in ep9_card["body_excerpt"]
    assert ep9_card["ending_state"] == saved_tail
    assert ep9_brief["source"] == "episode_locked_content_version"
    assert ep9_brief["official_source"] == "episode_locked"
    assert ep9_brief["content_version_id"] == "locked-version-ep9"
    assert ep9_brief["content_hash"] == saved_hash
    assert "ordinary scene content" not in ep9_brief["body_excerpt"]


def _create_enrich_schema(engine):
    ProjectV2.__table__.create(bind=engine)
    Episode.__table__.create(bind=engine)
    Scene.__table__.create(bind=engine)
    ContentVersion.__table__.create(bind=engine)
    EvidenceEvent.__table__.create(bind=engine)


def test_enrich_request_uses_direct_previous_locked_official_source_map(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'locked-official-source.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _create_enrich_schema(engine)

    locked_content = "\n".join([
        "safe official source line",
        "safe official ending carryover",
    ])
    locked_file = tmp_path / "locked-ep9.md"
    locked_file.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()

    with Session() as db:
        db.add(ProjectV2(
            id="project-official-source",
            name="official source",
            config="{}",
            workspace_path=str(tmp_path),
        ))
        db.add(Episode(
            id="episode-9",
            project_id="project-official-source",
            episode_number=9,
            title="Episode 9",
            status="completed",
        ))
        db.add(Scene(
            id="scene-9-1",
            episode_id="episode-9",
            scene_number=1,
            content="ordinary scene content must not become source",
        ))
        version = ContentVersion(
            id="locked-version-ep9",
            project_id="project-official-source",
            episode_number=9,
            scene_number=0,
            version_code="v001",
            content_path=str(locked_file),
            content_hash=locked_hash,
        )
        db.add(version)
        db.add(EvidenceEvent(
            project_id="project-official-source",
            event_type="episode_locked",
            target_type="episode",
            target_id="9",
            content_version_id=version.id,
            content_hash=version.content_hash,
        ))
        db.commit()

        enriched = enrich_testing_request_from_project(
            TestingScriptRequest(
                project_id="project-official-source",
                episode_no=10,
                materials=[{"title": "safe material"}],
                issue_feedback={"scope": "skip_material_lookup"},
            ),
            db,
        )

    ep9_brief = next(item for item in enriched.previous_episode_briefs if item["episode_no"] == 9)
    ep9_card = next(item for item in enriched.episode_memory_cards if item["episode_no"] == 9)

    assert ep9_brief["source"] == "episode_locked_content_version"
    assert ep9_brief["official_source"] == "episode_locked"
    assert ep9_brief["content_version_id"] == "locked-version-ep9"
    assert ep9_brief["content_hash"] == locked_hash
    assert ep9_brief["source_map"]["source"] == "episode_locked_content_version"
    assert ep9_card["source"] == "episode_locked_content_version"
    assert ep9_card["official_source"] == "episode_locked"
    assert "ordinary scene content" not in ep9_brief["body_excerpt"]


def test_enrich_request_blocks_scene_content_when_direct_previous_locked_official_missing(tmp_path):
    from app.services.short_drama_testing_enrich import PreviousOfficialSourceGateError

    engine = create_engine(
        f"sqlite:///{tmp_path / 'missing-locked-official.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _create_enrich_schema(engine)

    with Session() as db:
        db.add(ProjectV2(
            id="project-missing-official",
            name="missing official",
            config="{}",
            workspace_path=str(tmp_path),
        ))
        db.add(Episode(
            id="episode-1",
            project_id="project-missing-official",
            episode_number=1,
            title="Episode 1",
            status="completed",
        ))
        db.add(Scene(
            id="scene-1-1",
            episode_id="episode-1",
            scene_number=1,
            content="ordinary scene content cannot substitute locked official",
        ))
        db.commit()

        try:
            enrich_testing_request_from_project(
                TestingScriptRequest(
                    project_id="project-missing-official",
                    episode_no=2,
                    materials=[{"title": "safe material"}],
                    issue_feedback={"scope": "skip_material_lookup"},
                ),
                db,
            )
        except PreviousOfficialSourceGateError as exc:
            assert exc.reason_code == "previous_locked_official_source_missing"
        else:
            raise AssertionError("ordinary Scene.content must not substitute direct previous locked official source")


def test_enrich_request_rejects_stale_candidate_fallback_and_package_only_source(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reject-stale-source.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _create_enrich_schema(engine)

    locked_file = tmp_path / "locked-ep3.md"
    locked_content = "locked official safe source"
    locked_file.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()

    with Session() as db:
        db.add(ProjectV2(
            id="project-reject-stale",
            name="reject stale",
            config="{}",
            workspace_path=str(tmp_path),
        ))
        db.add(Episode(id="episode-3", project_id="project-reject-stale", episode_number=3, title="Episode 3"))
        version = ContentVersion(
            id="locked-version-ep3",
            project_id="project-reject-stale",
            episode_number=3,
            scene_number=0,
            version_code="v001",
            content_path=str(locked_file),
            content_hash=locked_hash,
        )
        db.add(version)
        db.add(EvidenceEvent(
            project_id="project-reject-stale",
            event_type="episode_locked",
            target_type="episode",
            target_id="3",
            content_version_id=version.id,
            content_hash=version.content_hash,
        ))
        db.commit()

        enriched = enrich_testing_request_from_project(
            TestingScriptRequest(
                project_id="project-reject-stale",
                episode_no=4,
                materials=[{"title": "safe material"}],
                issue_feedback={"scope": "skip_material_lookup"},
                previous_episode_briefs=[
                    {"episode_no": 3, "source": "latest_candidate", "body_excerpt": "stale candidate"},
                    {"episode_no": 3, "source": "fallback", "body_excerpt": "fallback blob"},
                    {"episode_no": 3, "source": "evidence_package", "body_excerpt": "package only"},
                ],
                episode_memory_cards=[
                    {"episode_no": 3, "source": "global_latest", "body_excerpt": "global latest"},
                ],
            ),
            db,
        )

    ep3_brief = next(item for item in enriched.previous_episode_briefs if item["episode_no"] == 3)
    ep3_card = next(item for item in enriched.episode_memory_cards if item["episode_no"] == 3)

    assert ep3_brief["source"] == "episode_locked_content_version"
    assert ep3_card["source"] == "episode_locked_content_version"
    assert ep3_brief["content_version_id"] == "locked-version-ep3"
    assert "stale candidate" not in ep3_brief["body_excerpt"]
    assert "fallback blob" not in ep3_brief["body_excerpt"]
    assert "package only" not in ep3_brief["body_excerpt"]
    assert "global latest" not in ep3_card["body_excerpt"]


def test_enrich_request_rejects_locked_file_outside_project_workspace(tmp_path):
    from app.services.short_drama_testing_enrich import PreviousOfficialSourceGateError

    engine = create_engine(
        f"sqlite:///{tmp_path / 'reject-outside-workspace.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _create_enrich_schema(engine)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    locked_content = "locked official safe source outside workspace"
    locked_file = outside / "locked-ep2.md"
    locked_file.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()

    with Session() as db:
        db.add(ProjectV2(
            id="project-outside-source",
            name="outside source",
            config="{}",
            workspace_path=str(workspace),
        ))
        db.add(Episode(id="episode-2", project_id="project-outside-source", episode_number=2, title="Episode 2"))
        version = ContentVersion(
            id="locked-version-outside",
            project_id="project-outside-source",
            episode_number=2,
            scene_number=0,
            version_code="v001",
            content_path=str(locked_file),
            content_hash=locked_hash,
        )
        db.add(version)
        db.add(EvidenceEvent(
            project_id="project-outside-source",
            event_type="episode_locked",
            target_type="episode",
            target_id="2",
            content_version_id=version.id,
            content_hash=version.content_hash,
        ))
        db.commit()

        try:
            enrich_testing_request_from_project(
                TestingScriptRequest(
                    project_id="project-outside-source",
                    episode_no=3,
                    materials=[{"title": "safe material"}],
                    issue_feedback={"scope": "skip_material_lookup"},
                ),
                db,
            )
        except PreviousOfficialSourceGateError as exc:
            assert exc.reason_code == "previous_locked_official_file_outside_workspace"
        else:
            raise AssertionError("locked official file path outside project workspace must be rejected")
