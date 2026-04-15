import json

import utils.trade_logs as trade_logs


def test_append_trade_log_creates_dated_file_and_writes_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_logs, "_BASE_DIR", tmp_path)

    path = trade_logs.append_trade_log("completed", [{"symbol": "NABIL", "qty": "10"}])

    assert path is not None
    assert path.parent.parent == tmp_path
    payload = json.loads(path.read_text())
    assert payload == [{"symbol": "NABIL", "qty": "10"}]


def test_append_trade_log_merges_with_existing_list(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_logs, "_BASE_DIR", tmp_path)

    trade_logs.append_trade_log("completed", [{"symbol": "A"}])
    trade_logs.append_trade_log("completed", [{"symbol": "B"}])

    path = trade_logs._path_for("completed")
    payload = json.loads(path.read_text())
    assert [entry["symbol"] for entry in payload] == ["A", "B"]


def test_append_trade_log_returns_none_for_empty_input(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_logs, "_BASE_DIR", tmp_path)

    assert trade_logs.append_trade_log("completed", []) is None
    assert trade_logs.append_trade_log("completed", [None, {}]) is None


def test_append_trade_log_ignores_corrupt_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_logs, "_BASE_DIR", tmp_path)

    target = trade_logs._path_for("market")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not-json")

    trade_logs.append_trade_log("market", [{"symbol": "A"}])

    payload = json.loads(target.read_text())
    assert payload == [{"symbol": "A"}]
