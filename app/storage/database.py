"""
SQLite tabanlı event + deduplication store.

Thread-safe: her thread kendi connection'ını açar (SQLite gereksinimi), WAL modu
ile çoklu okuma + tek yazma sorunsuz. Camera worker'lar yazar, Shopify worker
ve Admin Panel okur.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no          TEXT NOT NULL,
    camera_id         INTEGER NOT NULL,
    camera_name       TEXT NOT NULL,
    detected_at       TIMESTAMP NOT NULL,
    snapshot_path     TEXT,
    shopify_status    TEXT DEFAULT 'pending',  -- pending / success / failed / not_found
    shopify_error     TEXT,
    shopify_synced_at TIMESTAMP,
    retry_count       INTEGER DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_order_no ON events(order_no);
CREATE INDEX IF NOT EXISTS idx_detected_at ON events(detected_at);
CREATE INDEX IF NOT EXISTS idx_shopify_status ON events(shopify_status);
CREATE INDEX IF NOT EXISTS idx_dedup ON events(order_no, camera_id, detected_at);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript(SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------ #
    #  Yazma (camera + shopify worker)
    # ------------------------------------------------------------------ #
    def is_duplicate(self, order_no: str, camera_id: int, window_seconds: int) -> bool:
        """Aynı sipariş + aynı kamerada son N saniye içinde okundu mu?"""
        if window_seconds <= 0:
            return False
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        row = (
            self._conn()
            .execute(
                """
            SELECT 1 FROM events
            WHERE order_no = ? AND camera_id = ? AND detected_at >= ?
            LIMIT 1
            """,
                (order_no, camera_id, cutoff),
            )
            .fetchone()
        )
        return row is not None

    def insert_event(
        self,
        order_no: str,
        camera_id: int,
        camera_name: str,
        detected_at: datetime,
        snapshot_path: str | None = None,
    ) -> int:
        cur = self._conn().execute(
            """
            INSERT INTO events (order_no, camera_id, camera_name, detected_at, snapshot_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_no, camera_id, camera_name, detected_at, snapshot_path),
        )
        self._conn().commit()
        return cur.lastrowid

    def mark_shopify_success(self, event_id: int):
        self._conn().execute(
            """
            UPDATE events
            SET shopify_status='success', shopify_synced_at=CURRENT_TIMESTAMP, shopify_error=NULL
            WHERE id=?
            """,
            (event_id,),
        )
        self._conn().commit()

    def mark_shopify_failed(self, event_id: int, error: str, status: str = "failed"):
        """status: 'failed' (retry edilebilir) veya 'not_found' (sipariş yok)."""
        self._conn().execute(
            """
            UPDATE events
            SET shopify_status=?, shopify_error=?, retry_count=retry_count+1
            WHERE id=?
            """,
            (status, (error or "")[:500], event_id),
        )
        self._conn().commit()

    def get_pending_events(self, max_retries: int = 5, limit: int = 50) -> list[dict]:
        rows = (
            self._conn()
            .execute(
                """
            SELECT * FROM events
            WHERE shopify_status IN ('pending', 'failed')
              AND retry_count < ?
            ORDER BY detected_at ASC
            LIMIT ?
            """,
                (max_retries, limit),
            )
            .fetchall()
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Okuma / yönetim (Admin Panel)
    # ------------------------------------------------------------------ #
    def get_event(self, event_id: int) -> dict | None:
        row = self._conn().execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return dict(row) if row else None

    def _build_filter(
        self,
        order_no: str | None,
        camera_id: int | None,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
    ) -> tuple[str, list]:
        clauses, params = [], []
        if order_no:
            clauses.append("order_no LIKE ?")
            params.append(f"%{order_no}%")
        if camera_id is not None:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if status:
            clauses.append("shopify_status = ?")
            params.append(status)
        if date_from:
            clauses.append("detected_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("detected_at <= ?")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def search_events(
        self,
        order_no: str | None = None,
        camera_id: int | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._build_filter(order_no, camera_id, status, date_from, date_to)
        rows = (
            self._conn()
            .execute(
                f"SELECT * FROM events{where} ORDER BY detected_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
            .fetchall()
        )
        return [dict(r) for r in rows]

    def count_events(
        self,
        order_no: str | None = None,
        camera_id: int | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        where, params = self._build_filter(order_no, camera_id, status, date_from, date_to)
        row = self._conn().execute(f"SELECT COUNT(*) AS c FROM events{where}", params).fetchone()
        return row["c"]

    def requeue_event(self, event_id: int) -> bool:
        """not_found/failed bir event'i tekrar 'pending' yapar (retry sayacını sıfırlar)."""
        cur = self._conn().execute(
            """
            UPDATE events
            SET shopify_status='pending', retry_count=0, shopify_error=NULL
            WHERE id=?
            """,
            (event_id,),
        )
        self._conn().commit()
        return cur.rowcount > 0

    def stats(self) -> dict:
        conn = self._conn()
        by_status = {
            r["shopify_status"]: r["c"]
            for r in conn.execute(
                "SELECT shopify_status, COUNT(*) AS c FROM events GROUP BY shopify_status"
            ).fetchall()
        }
        total = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        today = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE date(detected_at)=date('now','localtime')"
        ).fetchone()["c"]
        by_camera = [
            dict(r)
            for r in conn.execute(
                """
                SELECT camera_id, camera_name, COUNT(*) AS count,
                       MAX(detected_at) AS last_detected_at
                FROM events GROUP BY camera_id, camera_name ORDER BY camera_id
                """
            ).fetchall()
        ]
        return {
            "total": total,
            "today": today,
            "by_status": by_status,
            "pending": by_status.get("pending", 0) + by_status.get("failed", 0),
            "by_camera": by_camera,
        }
