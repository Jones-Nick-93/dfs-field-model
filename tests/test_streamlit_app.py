from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_demo_loads_without_exceptions() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "Synthetic demo"
    assert app.radio[0].value == "Overview"
    assert len(app.metric) >= 9
    assert not app.tabs
    assert any("Synthetic demo" in caption.value for caption in app.caption)
