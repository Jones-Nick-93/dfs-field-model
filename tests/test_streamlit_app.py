from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_demo_loads_without_exceptions() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "Start here: same ownership"
    assert any("Three times" in heading.value for heading in app.subheader)
    app.sidebar.radio[0].set_value("Synthetic demo").run()
    assert not app.exception
    assert app.radio[0].value == "Overview"
    assert len(app.metric) >= 9
    assert not app.tabs
    assert any("Synthetic demo" in caption.value for caption in app.caption)
    for view in ["Ownership", "Pair structure", "Lineup inspector", "Method"]:
        app.radio[0].set_value(view).run()
        assert not app.exception
    app.sidebar.radio[0].set_value("Upload CSVs").run()
    assert not app.exception
    assert len(app.sidebar.get("file_uploader")) == 2
