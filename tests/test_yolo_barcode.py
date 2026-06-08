"""
YOLO barkod tespit testleri.

cv2 yoksa atlanır. YOLO modeli (ultralytics) ve pyzbar mock'lanır → gerçek
torch/model/barkod görüntüsü gerekmez; kutu→kırpma→pyzbar→regex/normalize akışı
test edilir.
"""

import pytest

pytest.importorskip("cv2")

import numpy as np  # noqa: E402

from app.detection import yolo_barcode as yb  # noqa: E402
from app.detection.yolo_barcode import YoloBarcodeDetector  # noqa: E402


class _FakeBoxes:
    def __init__(self, boxes):
        # ultralytics: result.boxes.xyxy.tolist()
        class _XY:
            def __init__(self, b):
                self._b = b

            def tolist(self):
                return self._b

        self.xyxy = _XY(boxes)


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = _FakeBoxes(boxes)


class _FakeModel:
    def __init__(self, boxes):
        self._boxes = boxes

    def predict(self, frame, conf=None, verbose=None):
        return [_FakeResult(self._boxes)]


class _Decoded:
    def __init__(self, value, type_="EAN13"):
        self.data = value.encode()
        self.type = type_


@pytest.fixture
def frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def _patch_pyzbar(monkeypatch, decoded_list):
    """yolo_barcode içindeki pyzbar.decode'u sahteler."""
    import pyzbar.pyzbar as pz

    monkeypatch.setattr(pz, "decode", lambda img, symbols=None: decoded_list)


def _detector_with_model(monkeypatch, boxes, **kwargs):
    det = YoloBarcodeDetector(symbols=None, **kwargs)
    det._model = _FakeModel(boxes)  # model yüklemeyi bypass et
    return det


def test_detects_barcode_in_box(monkeypatch, frame):
    _patch_pyzbar(monkeypatch, [_Decoded("7137311942243")])
    det = _detector_with_model(monkeypatch, boxes=[[400, 200, 700, 260]])
    results = det.detect(frame)
    assert len(results) == 1
    assert results[0].normalized == "7137311942243"
    assert results[0].symbol_type.startswith("YOLO+")


def test_no_box_no_result(monkeypatch, frame):
    _patch_pyzbar(monkeypatch, [_Decoded("7137311942243")])
    det = _detector_with_model(monkeypatch, boxes=[])  # YOLO hiç kutu bulamadı
    assert det.detect(frame) == []


def test_regex_filters_non_order(monkeypatch, frame):
    # 5 haneli → regex ^\d{6,20}$ ile elenir
    _patch_pyzbar(monkeypatch, [_Decoded("12345")])
    det = _detector_with_model(monkeypatch, boxes=[[400, 200, 700, 260]])
    assert det.detect(frame) == []


def test_dedup_same_value(monkeypatch, frame):
    _patch_pyzbar(monkeypatch, [_Decoded("7137311942243"), _Decoded("7137311942243")])
    det = _detector_with_model(monkeypatch, boxes=[[400, 200, 700, 260]])
    results = det.detect(frame)
    assert len(results) == 1  # aynı değer bir kez


def test_add_hash_prefix(monkeypatch, frame):
    _patch_pyzbar(monkeypatch, [_Decoded("939146")])
    det = _detector_with_model(
        monkeypatch, boxes=[[400, 200, 700, 260]], order_regex=r"^#?\d{6,10}$", add_hash_prefix=True
    )
    assert det.detect(frame)[0].normalized == "#939146"


def test_box_padding_clamped_to_bounds(monkeypatch, frame):
    """Kenardaki kutu pad ile taşmamalı (negatif/aşan index olmamalı)."""
    _patch_pyzbar(monkeypatch, [_Decoded("7137311942243")])
    det = _detector_with_model(monkeypatch, boxes=[[0, 0, 50, 50]], pad=20)
    # crop boş olmamalı, hata fırlamamalı
    assert det.detect(frame)[0].normalized == "7137311942243"


def test_to_gid_via_default_path():
    # model_path varsayılanı bozulmamış olmalı (image gömme ile tutarlı)
    assert yb.DEFAULT_MODEL_PATH == "models/barcode_yolov8s.pt"
