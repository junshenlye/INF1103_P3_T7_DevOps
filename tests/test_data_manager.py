import stat

from src import data_manager


def build_record(record_id, module="INF1103", revision=1):
    return {
        "record_id": record_id,
        "module": module,
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "priority": "HIGH",
        "status": "READY",
        "missing_fields": [],
        "issues": [],
        "revision": revision,
    }


def test_save_load_latest_and_filter_records(tmp_path):
    data_file = tmp_path / "schedules.json"
    first = build_record("record-001")
    revised = build_record("record-001", revision=2)
    other = build_record("record-002", module="INF1104")

    assert data_manager.save_records([first, other, revised], str(data_file)) is True
    loaded = data_manager.load_records(str(data_file))

    assert data_manager.get_latest_record(loaded, "record-001") == revised
    assert data_manager.next_revision(loaded, "record-001") == 3
    assert data_manager.filter_records(loaded, module="INF1104") == [other]


def test_corrupt_store_is_not_overwritten(tmp_path):
    data_file = tmp_path / "schedules.json"
    data_file.write_text("not-json", encoding="utf-8")

    saved = data_manager.save_record_revision(
        build_record("record-001"),
        str(data_file),
    )

    assert saved is False
    assert data_file.read_text(encoding="utf-8") == "not-json"


def test_atomic_store_is_private_and_leaves_no_temporary_file(tmp_path):
    data_file = tmp_path / "schedules.json"

    assert data_manager.save_records(
        [build_record("record-001")],
        str(data_file),
    ) is True

    assert stat.S_IMODE(data_file.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".schedules.json.*.tmp")) == []


def test_invalid_contract_is_not_saved(tmp_path):
    data_file = tmp_path / "schedules.json"

    assert data_manager.save_records(
        [{"record_id": "incomplete"}],
        str(data_file),
    ) is False
    assert data_file.exists() is False


def test_module_profiles_are_separate_private_metadata(tmp_path):
    module_file = tmp_path / "modules.json"

    assert data_manager.save_module_profile("inf1103", 12, str(module_file)) is True

    assert data_manager.load_module_profiles(str(module_file)) == {
        "INF1103": {"credits": 12.0}
    }
    assert stat.S_IMODE(module_file.stat().st_mode) == 0o600


def test_bulk_append_is_all_or_nothing(tmp_path):
    data_file = tmp_path / "schedules.json"
    existing = build_record("record-001")
    assert data_manager.save_records([existing], str(data_file)) is True
    valid = build_record("record-002")
    duplicate = build_record("record-001")

    assert data_manager.save_record_revisions(
        [valid, duplicate],
        str(data_file),
    ) is False
    assert data_manager.load_records(str(data_file)) == [existing]

    assert data_manager.save_record_revisions([valid], str(data_file)) is True
    assert data_manager.load_records(str(data_file)) == [existing, valid]
