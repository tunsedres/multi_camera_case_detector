"""
Barkod tespit testleri.

cv2/pyzbar yoksa atlanır (CI'da kuruludur). pyzbar.decode mock'lanır → gerçek
barkod görüntüsü gerekmez; regex filtre ve normalize mantığı test edilir.
"""

from collections import namedtuple

import pytest

pytest.importorskip("cv2")
pytest.importorskip("pyzbar.pyzbar")

import numpy as np  # noqa: E402

from app.detection import barcode as bc  # noqa: E402
from app.detection.barcode import BarcodeDetector  # noqa: E402

_Point = namedtuple("Point", "x y")
_Decoded = namedtuple("Decoded", "data type polygon")


def _fake_decode(values):
    """pyzbar.decode yerine geçer; verilen (value, type) listesini döner."""

    def decode(_img, symbols=None):
        return [
            _Decoded(data=v.encode(), type=t, polygon=[_Point(0, 0), _Point(1, 1)])
            for v, t in values
        ]

    return decode


@pytest.fixture
def frame():
    return np.zeros((20, 20, 3), dtype=np.uint8)


def test_detects_and_normalizes(monkeypatch, frame):
    monkeypatch.setattr(bc.pyzbar, "decode", _fake_decode([("1042", "CODE128")]))
    det = BarcodeDetector(order_regex=r"^#?\d{3,8}$", add_hash_prefix=True)
    results = det.detect(frame)
    assert len(results) == 1
    assert results[0].raw_value == "1042"
    assert results[0].normalized == "#1042"
    assert results[0].symbol_type == "CODE128"


def test_filters_non_matching(monkeypatch, frame):
    # ürün barkodu (13 hane EAN) sipariş regex'ine uymaz → elenir
    monkeypatch.setattr(
        bc.pyzbar, "decode", _fake_decode([("8691234567890", "EAN13"), ("1042", "CODE128")])
    )
    det = BarcodeDetector(order_regex=r"^#?\d{3,8}$")
    results = det.detect(frame)
    assert [r.raw_value for r in results] == ["1042"]


def test_no_hash_prefix(monkeypatch, frame):
    monkeypatch.setattr(bc.pyzbar, "decode", _fake_decode([("1042", "CODE128")]))
    det = BarcodeDetector(add_hash_prefix=False)
    assert det.detect(frame)[0].normalized == "1042"


def test_custom_regex(monkeypatch, frame):
    monkeypatch.setattr(bc.pyzbar, "decode", _fake_decode([("TR-2026-1234", "CODE128")]))
    det = BarcodeDetector(order_regex=r"^TR-\d{4}-\d+$", add_hash_prefix=False)
    assert det.detect(frame)[0].raw_value == "TR-2026-1234"


def test_symbol_resolution():
    det = BarcodeDetector(symbols=["CODE128", "QRCODE", "BILINMEYEN"])
    # geçerli iki sembol çözülür, bilinmeyen atlanır
    assert det.symbols is not None
    assert len(det.symbols) == 2
    # boş liste → None (hepsi taranır)
    assert BarcodeDetector(symbols=[]).symbols is None
