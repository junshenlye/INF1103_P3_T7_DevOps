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
