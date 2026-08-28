from __future__ import annotations

from pathlib import Path

from soundlink_warehouse_connector.state.store import StateStore


def test_state_save_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "sync_state.json"
    store = StateStore(path)
    store.set("last_sync", {"mode": "incremental", "date": "2026-08-28"})
    store.save()

    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()

    reloaded = StateStore(path)
    assert reloaded.get("last_sync") == {"mode": "incremental", "date": "2026-08-28"}
