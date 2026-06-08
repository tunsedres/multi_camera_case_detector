"""
Çoklu-kare oylama: OCR/barkod okumalarını zamansal olarak doğrular.

Neden: OCR tek karede ara sıra yanlış okuyabilir (#939146 yerine #339146). Bir
değeri Shopify'a yazmadan önce, kısa bir pencere içinde yeterince çok kez (eşik)
okunmuş olmasını şart koşarak tek-tük yanlış okumaları eleriz.

Worker her tespiti record() ile verir; bir değer pencere içinde 'min_votes' kez
görülünce ve henüz onaylanmamışsa confirmed değer döner (bir kez). Aynı değer
'cooldown' süresince tekrar onaylanmaz (tek event üretir).
"""

from __future__ import annotations

import time
from collections import deque


class DetectionVoter:
    def __init__(
        self,
        min_votes: int = 3,
        window_seconds: float = 4.0,
        cooldown_seconds: float = 15.0,
    ):
        if min_votes < 1:
            raise ValueError("min_votes >= 1 olmalı")
        self.min_votes = min_votes
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        # (timestamp, value) okumaları; pencere dışı olanlar atılır.
        self._reads: deque[tuple[float, str]] = deque()
        # value → son onay zamanı (cooldown için).
        self._confirmed_at: dict[str, float] = {}

    def record(self, value: str, now: float | None = None) -> str | None:
        """
        Bir okuma kaydeder. Değer pencere içinde eşiği geçtiyse ve cooldown'da
        değilse onaylanmış değeri döner; aksi halde None.
        """
        now = time.monotonic() if now is None else now
        self._reads.append((now, value))
        self._evict(now)

        # Cooldown: yakın zamanda onaylandıysa tekrar tetikleme.
        last = self._confirmed_at.get(value)
        if last is not None and (now - last) < self.cooldown_seconds:
            return None

        votes = sum(1 for _, v in self._reads if v == value)
        if votes >= self.min_votes:
            self._confirmed_at[value] = now
            # Bu değerin oylarını temizle ki hemen tekrar tetiklenmesin.
            self._reads = deque((t, v) for (t, v) in self._reads if v != value)
            return value
        return None

    def _evict(self, now: float) -> None:
        """Pencere dışı okumaları ve eski cooldown kayıtlarını at."""
        cutoff = now - self.window_seconds
        while self._reads and self._reads[0][0] < cutoff:
            self._reads.popleft()
        # Cooldown süresi geçmiş onayları unut (sözlük şişmesin).
        stale = [v for v, t in self._confirmed_at.items() if (now - t) >= self.cooldown_seconds]
        for v in stale:
            del self._confirmed_at[v]
