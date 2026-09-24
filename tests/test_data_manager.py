import stat

from src import data_manager


def build_record(record_id, module, status):
    return {
        "record_id": record_id,
        "module": module,
        "assessment_type": "Project",
        "deadline": "2026-10-15" if status == "READY" else None,
        "weightage": 30,
        "priority": "HIGH" if status == "READY" else None,
        "status": status,
        "missing_fields": [] if status == "READY" else ["deadline"],
        "issues": [],
        "revision": 1,
    }


def test_load_records_returns_empty_list_for_missing_file(tmp_path):
    assert data_manager.load_records(str(tmp_path / "missing.json")) == []


def test_load_records_returns_empty_list_for_corrupt_file(tmp_path):
    data_file = tmp_path / "corrupt.json"
    data_file.write_text("not-json", encoding="utf-8")

    assert data_manager.load_records(str(data_file)) == []


def test_save_load_and_filter_records(tmp_path):
    data_file = tmp_path / "schedules.json"
    records = [
        build_record("record-001", "INF1103", "READY"),
        build_record("record-002", "INF1104", "INCOMPLETE"),
        build_record("record-003", "INF1103", "INCOMPLETE"),
    ]

    assert data_manager.save_records(records, str(data_file)) is True
    loaded_records = data_manager.load_records(str(data_file))

    assert loaded_records == records
    assert data_manager.filter_records(loaded_records, module="INF1103") == [
        records[0],
        records[2],
    ]
    assert data_manager.filter_records(
        loaded_records,
        module="INF1103",
        status="INCOMPLETE",
    ) == [records[2]]


def test_load_records_ignores_contract_violations(tmp_path):
    data_file = tmp_path / "schedules.json"
    data_file.write_text('[{"record_id": "incomplete-shape"}]', encoding="utf-8")

    assert data_manager.load_records(str(data_file)) == []


def test_save_records_rejects_contract_violations(tmp_path):
    data_file = tmp_path / "schedules.json"

    assert data_manager.save_records([{"record_id": "incomplete-shape"}], str(data_file)) is False
    assert data_file.exists() is False


def test_latest_record_helpers_preserve_revision_history():
    revision_one = build_record("record-001", "INF1103", "INCOMPLETE")
    revision_two = build_record("record-001", "INF1103", "READY")
    revision_two["revision"] = 2
    other_record = build_record("record-002", "INF1104", "READY")
    records = [revision_one, other_record, revision_two]

    assert data_manager.get_record_history(records, "record-001") == [
        revision_one,
        revision_two,
    ]
    assert data_manager.get_latest_record(records, "record-001") == revision_two
    assert data_manager.next_revision(records, "record-001") == 3
    assert set(record["record_id"] for record in data_manager.latest_records(records)) == {
        "record-001",
        "record-002",
    }


def test_append_refuses_to_overwrite_corrupt_store(tmp_path):
    data_file = tmp_path / "schedules.json"
    data_file.write_text("not-json", encoding="utf-8")

    saved = data_manager.save_record_revision(
        build_record("record-001", "INF1103", "READY"),
        str(data_file),
    )

    assert saved is False
    assert data_file.read_text(encoding="utf-8") == "not-json"


def test_saved_store_is_private_and_leaves_no_temporary_file(tmp_path):
    data_file = tmp_path / "schedules.json"

    assert data_manager.save_records(
        [build_record("record-001", "INF1103", "READY")],
        str(data_file),
    ) is True

    assert stat.S_IMODE(data_file.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".schedules.json.*.tmp")) == []


def test_duplicate_record_revision_is_rejected(tmp_path):
    data_file = tmp_path / "schedules.json"
    record = build_record("record-001", "INF1103", "READY")

    assert data_manager.save_record_revision(record, str(data_file)) is True
    assert data_manager.save_record_revision(record, str(data_file)) is False
    assert data_manager.load_records(str(data_file)) == [record]


def test_module_profiles_are_separate_private_metadata(tmp_path):
    module_file = tmp_path / "modules.json"

    assert data_manager.save_module_profile(
        "inf1103",
        12,
        str(module_file),
    ) is True

    assert data_manager.load_module_profiles(str(module_file)) == {
        "INF1103": {"credits": 12.0}
    }
    assert stat.S_IMODE(module_file.stat().st_mode) == 0o600


def test_corrupt_module_profiles_are_not_overwritten(tmp_path):
    module_file = tmp_path / "modules.json"
    module_file.write_text("not-json", encoding="utf-8")

    saved = data_manager.save_module_profile("INF1103", 6, str(module_file))

    assert saved is False
    assert module_file.read_text(encoding="utf-8") == "not-json"


def test_bulk_append_saves_all_records_in_one_store_update(tmp_path):
    data_file = tmp_path / "schedules.json"
    first = build_record("record-001", "INF1103", "READY")
    second = build_record("record-002", "INF1103", "READY")

    saved = data_manager.save_record_revisions([first, second], str(data_file))

    assert saved is True
    assert data_manager.load_records(str(data_file)) == [first, second]


def test_bulk_append_rejects_entire_set_when_one_revision_is_invalid(tmp_path):
    data_file = tmp_path / "schedules.json"
    existing = build_record("record-001", "INF1103", "READY")
    assert data_manager.save_records([existing], str(data_file)) is True
    valid = build_record("record-002", "INF1103", "READY")
    invalid = build_record("record-001", "INF1103", "READY")

    saved = data_manager.save_record_revisions(
        [valid, invalid],
        str(data_file),
    )

    assert saved is False
    assert data_manager.load_records(str(data_file)) == [existing]
