"""Çoklu-kare oylama (DetectionVoter) testleri."""

from __future__ import annotations

import pytest

from app.detection.voting import DetectionVoter


def test_confirms_after_min_votes():
    v = DetectionVoter(min_votes=3, window_seconds=10, cooldown_seconds=10)
    assert v.record("#939146", now=0.0) is None  # 1
    assert v.record("#939146", now=0.5) is None  # 2
    assert v.record("#939146", now=1.0) == "#939146"  # 3 → onay


def test_single_wrong_read_does_not_confirm():
    v = DetectionVoter(min_votes=3, window_seconds=10, cooldown_seconds=10)
    v.record("#939146", now=0.0)
    v.record("#339146", now=0.3)  # tek-tük yanlış okuma
    v.record("#939146", now=0.6)
    # yanlış olan 1 oy → asla onaylanmaz
    assert v.record("#939146", now=0.9) == "#939146"
    # #339146 için ayrı oy gelmedikçe onaylanmaz
    assert v.record("#339146", now=1.2) is None


def test_votes_outside_window_expire():
    v = DetectionVoter(min_votes=3, window_seconds=2.0, cooldown_seconds=10)
    v.record("#939146", now=0.0)
    v.record("#939146", now=0.5)
    # 3. oy pencere dışında (ilk oy düşer) → henüz 2 oy
    assert v.record("#939146", now=3.0) is None


def test_cooldown_prevents_repeat_trigger():
    v = DetectionVoter(min_votes=2, window_seconds=10, cooldown_seconds=15)
    v.record("#939146", now=0.0)
    assert v.record("#939146", now=0.2) == "#939146"  # onay
    # cooldown içinde tekrar okunsa da yeni event yok
    v.record("#939146", now=1.0)
    assert v.record("#939146", now=2.0) is None
    # cooldown bitince tekrar onaylanabilir
    v.record("#939146", now=20.0)
    assert v.record("#939146", now=20.2) == "#939146"


def test_min_votes_one_triggers_immediately():
    v = DetectionVoter(min_votes=1, window_seconds=10, cooldown_seconds=0)
    assert v.record("#939146", now=0.0) == "#939146"


def test_two_valid_numbers_independent():
    v = DetectionVoter(min_votes=2, window_seconds=10, cooldown_seconds=10)
    v.record("#111111", now=0.0)
    v.record("#222222", now=0.1)
    assert v.record("#111111", now=0.2) == "#111111"
    assert v.record("#222222", now=0.3) == "#222222"


def test_invalid_min_votes():
    with pytest.raises(ValueError):
        DetectionVoter(min_votes=0)
