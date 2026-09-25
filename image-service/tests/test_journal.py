import json

import pytest

from image_service.journal import CorruptJournal, Journal


def test_receipt_survives_journal_reopen(tmp_path):
    receipt = {"event_id": "same_event", "error": {"code": "GENERATION_FAILED"}}
    with Journal(tmp_path) as journal:
        journal.save("attempt", "lease", receipt)
    with Journal(tmp_path) as journal:
        path, value = next(journal.pending())
        assert value["receipt"] == receipt
        assert "lease" not in path.name
        assert "Bearer" not in path.read_text(encoding="utf-8")
        journal.acknowledge(path)
        assert list(journal.pending()) == []


def test_journal_rejects_paths_and_concurrent_owner(tmp_path):
    with Journal(tmp_path) as journal:
        with pytest.raises(ValueError):
            journal.save("../escape", "lease", {})
        with pytest.raises(RuntimeError, match="already in use"), Journal(tmp_path):
            pass


@pytest.mark.parametrize("content", ["{", "{}", "[]", '{"attempt": "../x"}'])
def test_corrupt_journal_stops_without_discarding_evidence(tmp_path, content):
    path = tmp_path / "damaged.json"
    path.write_text(content, encoding="utf-8")
    with Journal(tmp_path) as journal, pytest.raises(CorruptJournal):
        list(journal.pending())
    assert path.read_text(encoding="utf-8") == content


def test_incomplete_write_is_not_a_receipt(tmp_path):
    (tmp_path / "orphan.pending").write_text(json.dumps({"incomplete": True}), encoding="utf-8")
    with Journal(tmp_path) as journal:
        assert list(journal.pending()) == []
