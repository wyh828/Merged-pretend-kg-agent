import xml.etree.ElementTree as ET
from techtrend.viz.svg import line_chart


def test_missing_last_fold_and_empty_series_render_without_false_connections():
    svg = line_chart([("model", [1.0, None, 2.0, None]), ("absent", [None] * 4)], ["a", "b", "c", "d"])
    root = ET.fromstring(svg)
    assert len(root.findall("polyline")) == 2
    assert len(root.findall("circle")) == 1
    assert "nan" not in svg


def test_nan_metrics_are_missing_points():
    ET.fromstring(line_chart([("model", [float("nan"), None])], ["a", "b"]))
