"""
Web panel ile orchestrator arasında paylaşılan bağımlılık taşıyıcısı.

FastAPI uygulaması bu context üzerinden DB, health, snapshot ve config'e erişir.
Ayrı modülde tutulur ki web ↔ app.py arasında döngüsel import olmasın.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import AppConfig
from app.monitoring.health import HealthRegistry
from app.settings import Settings
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore

logger = logging.getLogger("packing.web")


def _default_restart() -> None:
    """
    Süreci nazikçe sonlandırır → Docker `restart: unless-stopped` yeniden başlatır.

    PID'e SIGTERM gönderir; uvicorn bunu yakalayıp düzgün kapanır (worker'lar
    join edilir), süreç 0 ile çıkar, container yeniden ayağa kalkar (~2-3 sn).
    Web yanıtının dönebilmesi için kısa bir gecikmeyle ayrı thread'den tetiklenir.
    """

    def _kill():
        logger.warning("Panelden yeniden başlatma istendi — SIGTERM gönderiliyor.")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Timer(0.5, _kill).start()


@dataclass
class AppContext:
    db: Database
    health: HealthRegistry
    snapshots: SnapshotStore
    settings: Settings
    config: AppConfig
    version: str = "1.0.0"
    # Panelden kamera değişti → yeniden başlatma gerek (worker'lar boot'ta kurulur).
    # Mutable liste ki route'lar bayrağı set edebilsin (dataclass alanı reassign yerine).
    _restart_flag: list[bool] = field(default_factory=lambda: [False])
    # Yeniden başlatmayı tetikleyen callable (test'te stub'lanabilir).
    restart_fn: Callable[[], None] = _default_restart
    # Session cookie imzalama anahtarı (bir kez çözülür; her istekte değil).
    session_secret: str = field(default="")

    def __post_init__(self):
        if not self.session_secret:
            self.session_secret = self.settings.resolve_session_secret()

    @property
    def restart_needed(self) -> bool:
        return self._restart_flag[0]

    def mark_restart_needed(self) -> None:
        self._restart_flag[0] = True

    def request_restart(self) -> None:
        """Yeniden başlatmayı tetikler (süreç çıkar, Docker tekrar başlatır)."""
        self.restart_fn()
