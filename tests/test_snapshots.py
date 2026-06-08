"""Snapshot retention temizliği testleri (cv2 gerektirmez)."""

from datetime import datetime, timedelta

from app.storage.snapshots import SnapshotStore


def test_cleanup_removes_old_dirs(tmp_path):
    store = SnapshotStore(str(tmp_path / "snaps"), enabled=True)
    old = datetime.now() - timedelta(days=100)
    new = datetime.now() - timedelta(days=2)
    (store.base_dir / old.strftime("%Y-%m-%d")).mkdir(parents=True)
    (store.base_dir / new.strftime("%Y-%m-%d")).mkdir(parents=True)
    (store.base_dir / "rastgele-klasor").mkdir(parents=True)  # tarih değil → dokunulmaz

    removed = store.cleanup_old(retention_days=90)
    assert removed == 1
    assert not (store.base_dir / old.strftime("%Y-%m-%d")).exists()
    assert (store.base_dir / new.strftime("%Y-%m-%d")).exists()
    assert (store.base_dir / "rastgele-klasor").exists()


def test_cleanup_disabled_when_retention_zero(tmp_path):
    store = SnapshotStore(str(tmp_path / "snaps"), enabled=True)
    old = datetime.now() - timedelta(days=100)
    (store.base_dir / old.strftime("%Y-%m-%d")).mkdir(parents=True)
    assert store.cleanup_old(retention_days=0) == 0
    assert (store.base_dir / old.strftime("%Y-%m-%d")).exists()


def test_save_returns_none_when_disabled(tmp_path):
    store = SnapshotStore(str(tmp_path / "snaps"), enabled=False)
    assert store.save(None, 1, "#1001", datetime.now()) is None
