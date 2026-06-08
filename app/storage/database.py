"""
SQLite tabanlı event ve deduplication store.
Thread-safe (her thread kendi connection'ını açar).
"""
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no        TEXT NOT NULL,
    camera_id       INTEGER NOT NULL,
    camera_name     TEXT NOT NULL,
    detected_at     TIMESTAMP NOT NULL,
    snapshot_path   TEXT,
    shopify_status  TEXT DEFAULT 'pending',  -- pending / success / failed / not_found
    shopify_error   TEXT,
    shopify_synced_at TIMESTAMP,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_order_no ON events(order_no);
CREATE INDEX IF NOT EXISTS idx_detected_at ON events(detected_at);
CREATE INDEX IF NOT EXISTS idx_shopify_status ON events(shopify_status);
CREATE INDEX IF NOT EXISTS idx_dedup ON events(order_no, camera_id, detected_at);
"""


class Database:
    """Tek SQLite veritabanı, thread-safe."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        """Her thread için ayrı connection (SQLite gereksinimi)."""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            # WAL modu: birden fazla okuma + tek yazma için ideal
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def is_duplicate(self, order_no: str, camera_id: int, window_seconds: int) -> bool:
        """
        Aynı sipariş, aynı kamerada, son N saniye içinde okundu mu?
        Farklı kameradan okunmuş olabilir - bu dedup değil, yeni event.
        """
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        row = self._conn().execute(
            """
            SELECT 1 FROM events
            WHERE order_no = ? AND camera_id = ? AND detected_at >= ?
            LIMIT 1
            """,
            (order_no, camera_id, cutoff),
        ).fetchone()
        return row is not None

    def insert_event(
        self,
        order_no: str,
        camera_id: int,
        camera_name: str,
        detected_at: datetime,
        snapshot_path: Optional[str] = None,
    ) -> int:
        """Yeni tespit kaydı, ID döner."""
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
            (status, error[:500], event_id),
        )
        self._conn().commit()

    def get_pending_events(self, max_retries: int = 5, limit: int = 50):
        """Shopify'a yazılamamış, retry edilmesi gereken eventler."""
        rows = self._conn().execute(
            """
            SELECT * FROM events
            WHERE shopify_status IN ('pending', 'failed')
              AND retry_count < ?
            ORDER BY detected_at ASC
            LIMIT ?
            """,
            (max_retries, limit),
        ).fetchall()
        return [dict(r) for r in rows]
