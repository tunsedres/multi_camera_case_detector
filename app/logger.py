"""
Logging setup — hem konsola hem dosyaya (rotating) yazar.

Child logger'lar ('packing.worker', 'packing.shopify' vb.) propagate ile bu
logger'ın handler'larını kullanır; tek noktadan format/rotation yönetilir.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(
    name: str = "packing",
    log_dir: str = "logs",
    level: str | None = None,
) -> logging.Logger:
    """Hem konsola hem dosyaya yazan logger oluşturur (idempotent)."""
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Tekrar setup edilirse handler'lar çoğalmasın
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        f"{log_dir}/app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
