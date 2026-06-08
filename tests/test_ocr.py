"""
OCR sipariş-no tespit testleri.

cv2/pytesseract yoksa atlanır. pytesseract.image_to_data mock'lanır → gerçek
görüntü/tesseract binary'si gerekmez; regex filtre, güven eşiği, normalize ve
sıralama mantığı test edilir.
"""

import pytest

pytest.importorskip("cv2")
pytest.importorskip("pytesseract")

import numpy as np  # noqa: E402

from app.detection import ocr as ocr_mod  # noqa: E402
from app.detection.ocr import OCRDetector  # noqa: E402


def _fake_image_to_data(words):
    """pytesseract.image_to_data yerine; (text, conf) listesini DICT olarak döner."""

    def fn(_img, config=None, output_type=None):
        return {
            "text": [w for w, _ in words],
            "conf": [c for _, c in words],
        }

    return fn


@pytest.fixture
def frame():
    return np.zeros((100, 200, 3), dtype=np.uint8)


def test_reads_order_number(monkeypatch, frame):
    monkeypatch.setattr(
        ocr_mod.pytesseract,
        "image_to_data",
        _fake_image_to_data([("#939141", 92.0), ("Batch:", 80.0)]),
    )
    det = OCRDetector()
    results = det.detect(frame)
    assert len(results) == 1
    assert results[0].normalized == "#939141"
    assert results[0].symbol_type == "OCR"


def test_adds_hash_prefix(monkeypatch, frame):
    monkeypatch.setattr(
        ocr_mod.pytesseract, "image_to_data", _fake_image_to_data([("939141", 90.0)])
    )
    det = OCRDetector(add_hash_prefix=True)
    assert det.detect(frame)[0].normalized == "#939141"


def test_low_confidence_filtered(monkeypatch, frame):
    monkeypatch.setattr(
        ocr_mod.pytesseract, "image_to_data", _fake_image_to_data([("939141", 40.0)])
    )
    det = OCRDetector(min_confidence=60.0)
    assert det.detect(frame) == []


def test_non_matching_text_filtered(monkeypatch, frame):
    # harf içeren / çok uzun → regex'e uymaz
    monkeypatch.setattr(
        ocr_mod.pytesseract,
        "image_to_data",
        _fake_image_to_data([("kotendy", 95.0), ("7137311942243", 95.0)]),
    )
    det = OCRDetector(order_regex=r"^#?\d{6,10}$")
    assert det.detect(frame) == []  # 13 hane > 10, harf elenir


def test_short_partial_reads_filtered(monkeypatch, frame):
    """6 haneden kısa yarım OCR okumaları (#474, #939) elenmeli."""
    monkeypatch.setattr(
        ocr_mod.pytesseract,
        "image_to_data",
        _fake_image_to_data([("474", 95.0), ("939", 95.0), ("12345", 95.0)]),
    )
    det = OCRDetector(order_regex=r"^#?\d{6,10}$")
    assert det.detect(frame) == []  # hepsi <6 hane

    # 6 haneli tam okuma geçer
    monkeypatch.setattr(
        ocr_mod.pytesseract, "image_to_data", _fake_image_to_data([("939146", 95.0)])
    )
    assert det.detect(frame)[0].normalized == "#939146"


def test_sorted_by_confidence_and_deduped(monkeypatch, frame):
    monkeypatch.setattr(
        ocr_mod.pytesseract,
        "image_to_data",
        _fake_image_to_data([("939141", 70.0), ("123456", 95.0), ("939141", 88.0)]),
    )
    det = OCRDetector()
    results = det.detect(frame)
    norms = [r.normalized for r in results]
    assert norms == ["#123456", "#939141"]  # en güvenli ilk, tekrar yok


def test_tesseract_error_returns_empty(monkeypatch, frame):
    def boom(*a, **k):
        raise ocr_mod.pytesseract.TesseractError(1, "yok")

    monkeypatch.setattr(ocr_mod.pytesseract, "image_to_data", boom)
    assert OCRDetector().detect(frame) == []
