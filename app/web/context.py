"""
Web panel ile orchestrator arasında paylaşılan bağımlılık taşıyıcısı.

FastAPI uygulaması bu context üzerinden DB, health, snapshot ve config'e erişir.
Ayrı modülde tutulur ki web ↔ app.py arasında döngüsel import olmasın.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import AppConfig
from app.monitoring.health import HealthRegistry
from app.settings import Settings
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore


@dataclass
class AppContext:
    db: Database
    health: HealthRegistry
    snapshots: SnapshotStore
    settings: Settings
    config: AppConfig
    version: str = "1.0.0"
