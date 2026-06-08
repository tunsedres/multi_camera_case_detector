"""SQLite event store testleri."""

from datetime import datetime, timedelta


def _insert(db, order_no="#1001", camera_id=1, name="Masa 1", when=None):
    return db.insert_event(order_no, camera_id, name, when or datetime.now())


def test_insert_and_get(db):
    eid = _insert(db)
    ev = db.get_event(eid)
    assert ev["order_no"] == "#1001"
    assert ev["shopify_status"] == "pending"


def test_dedup_same_camera(db):
    _insert(db)
    assert db.is_duplicate("#1001", 1, 30) is True
    # farklı kamera dedup değil
    assert db.is_duplicate("#1001", 2, 30) is False


def test_dedup_window_expired(db):
    db.insert_event("#1001", 1, "Masa 1", datetime.now() - timedelta(seconds=120))
    assert db.is_duplicate("#1001", 1, 30) is False


def test_dedup_zero_window_disables(db):
    _insert(db)
    assert db.is_duplicate("#1001", 1, 0) is False


def test_pending_and_success_flow(db):
    eid = _insert(db)
    assert len(db.get_pending_events()) == 1
    db.mark_shopify_success(eid)
    assert db.get_pending_events() == []
    assert db.get_event(eid)["shopify_status"] == "success"


def test_failed_increments_retry_and_caps(db):
    eid = _insert(db)
    for _ in range(5):
        db.mark_shopify_failed(eid, "boom")
    # retry_count 5 >= max_retries(5) → artık pending listesinde değil
    assert db.get_pending_events(max_retries=5) == []
    assert db.get_event(eid)["retry_count"] == 5


def test_not_found_status(db):
    eid = _insert(db)
    db.mark_shopify_failed(eid, "yok", status="not_found")
    assert db.get_event(eid)["shopify_status"] == "not_found"


def test_requeue(db):
    eid = _insert(db)
    db.mark_shopify_failed(eid, "yok", status="not_found")
    assert db.requeue_event(eid) is True
    ev = db.get_event(eid)
    assert ev["shopify_status"] == "pending"
    assert ev["retry_count"] == 0
    assert db.requeue_event(999999) is False


def test_search_filters(db):
    _insert(db, "#1001", 1, "Masa 1")
    _insert(db, "#1002", 2, "Masa 2")
    assert db.count_events() == 2
    assert len(db.search_events(order_no="1001")) == 1
    assert len(db.search_events(camera_id=2)) == 1
    assert db.count_events(status="pending") == 2


def test_stats(db):
    e1 = _insert(db, "#1001")
    _insert(db, "#1002")
    db.mark_shopify_success(e1)
    stats = db.stats()
    assert stats["total"] == 2
    assert stats["by_status"]["success"] == 1
    assert stats["by_status"]["pending"] == 1
    assert len(stats["by_camera"]) >= 1
