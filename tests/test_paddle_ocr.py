"""
PaddleOCR sipariş-no tespit testleri.

cv2 yoksa atlanır. PaddleOCR engine'i (paddleocr) mock'lanır → gerçek paddle/model
gerekmez; regex filtre, güven eşiği, normalize ve sıralama mantığı test edilir.
"""

import pytest

pytest.importorskip("cv2")

import numpy as np  # noqa: E402

from app.detection.paddle_ocr import PaddleOCRDetector  # noqa: E402


class _FakeEngine:
    """paddleocr.PaddleOCR.ocr(frame, cls=) çıktısını taklit eder."""

    def __init__(self, lines):
        # lines: [(text, conf), ...]  → PaddleOCR formatı: [[ [box], (text, conf) ], ...]
        self._lines = lines

    def ocr(self, frame, cls=False):
        return [[[None, (t, c)] for t, c in self._lines]]


@pytest.fixture
def frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def _det(lines, **kwargs):
    d = PaddleOCRDetector(**kwargs)
    d._ocr = _FakeEngine(lines)  # engine yüklemeyi bypass et
    return d


def test_reads_order_number(frame):
    d = _det([("#939146", 0.97), ("Batch: 10476", 0.95)])
    res = d.detect(frame)
    assert len(res) == 1
    assert res[0].normalized == "#939146"
    assert res[0].symbol_type == "PADDLE"


def test_adds_hash_prefix(frame):
    d = _det([("939146", 0.96)], add_hash_prefix=True)
    assert d.detect(frame)[0].normalized == "#939146"


def test_low_confidence_filtered(frame):
    d = _det([("939146", 0.50)], min_confidence=0.80)
    assert d.detect(frame) == []


def test_non_matching_filtered(frame):
    # harf / çok uzun → regex'e uymaz
    d = _det([("kotendy", 0.99), ("7137311942243", 0.99)], order_regex=r"^#?\d{6,10}$")
    assert d.detect(frame) == []


def test_strips_spaces(frame):
    # PaddleOCR bazen '# 939146' gibi boşluklu döner
    d = _det([("# 939146", 0.95)])
    assert d.detect(frame)[0].normalized == "#939146"


def test_sorted_by_confidence_and_deduped(frame):
    d = _det([("939146", 0.70), ("123456", 0.98), ("939146", 0.85)])
    norms = [r.normalized for r in d.detect(frame)]
    assert norms == ["#123456", "#939146"]  # en güvenli ilk, tekrar yok


def test_empty_result(frame):
    d = _det([])
    assert d.detect(frame) == []
