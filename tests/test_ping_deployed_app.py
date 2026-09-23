"""ping_deployed_app.py is mostly real browser automation (not practical to unit test
without a real Playwright session), but the frame-selection logic is a plain function
worth locking in - Streamlit Community Cloud wraps the app in an iframe alongside an
unrelated statuspage.io status widget, and picking the wrong one is a real, easy mistake
(hit it once by hand while building this: `page.frames` in DOM order returned the status
widget before the actual app frame)."""
import ping_deployed_app


class _FakeFrame:
    def __init__(self, url):
        self.url = url


class _FakePage:
    def __init__(self, urls):
        self.frames = [_FakeFrame(u) for u in urls]


def test_find_app_frame_skips_unrelated_frames():
    page = _FakePage([
        "https://birdzone.streamlit.app/",
        "https://qjmnz4vd2y07.statuspage.io/embed/frame",
        "https://birdzone.streamlit.app/~/+/",
    ])
    frame = ping_deployed_app._find_app_frame(page)
    assert frame is not None
    assert frame.url == "https://birdzone.streamlit.app/~/+/"


def test_find_app_frame_returns_none_when_not_present():
    page = _FakePage(["https://birdzone.streamlit.app/", "https://qjmnz4vd2y07.statuspage.io/embed/frame"])
    assert ping_deployed_app._find_app_frame(page) is None


def test_find_app_frame_requires_both_domain_and_path_markers():
    # a frame that matches only one of the two conditions must not be picked -
    # guards against a too-loose match accidentally grabbing an unrelated frame
    page = _FakePage(["https://example.com/~/+/", "https://birdzone.streamlit.app/some/other/path"])
    assert ping_deployed_app._find_app_frame(page) is None
