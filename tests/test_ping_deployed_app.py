"""ping_deployed_app.py is mostly real browser automation (not practical to unit test
without a real Playwright session), but the frame-selection logic is a plain function
worth locking in - Streamlit Community Cloud wraps the app in an iframe alongside an
unrelated statuspage.io status widget, and picking the wrong one is a real, easy mistake
(hit it once by hand while building this: `page.frames` in DOM order returned the status
widget before the actual app frame)."""
import io

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


class _FakeLocator:
    """Stands in for a Playwright locator - visible() controls whether .wait_for()
    raises (mirroring Playwright's real timeout behavior when an element never
    appears), and .click() just records that it happened."""

    def __init__(self, visible: bool):
        self.visible = visible
        self.clicked = False

    def wait_for(self, state="visible", timeout=None):
        if not self.visible:
            raise TimeoutError("element never became visible")

    def click(self):
        self.clicked = True


class _FakePollingPage:
    """A page whose .frames only "appear" after enough .wait_for_timeout() calls -
    stands in for a real cold start, where the app's iframe doesn't exist yet and
    shows up only once the site finishes booting."""

    def __init__(self, frames_appear_after_polls: int, wake_button_visible: bool = False):
        self._frames_appear_after_polls = frames_appear_after_polls
        self._polls = 0
        self._wake_locator = _FakeLocator(visible=wake_button_visible)

    @property
    def frames(self):
        if self._polls >= self._frames_appear_after_polls:
            return [_FakeFrame("https://birdzone.streamlit.app/~/+/")]
        return [_FakeFrame("https://birdzone.streamlit.app/")]

    def wait_for_timeout(self, ms):
        self._polls += 1

    def get_by_role(self, role, name=None):
        return self._wake_locator


def test_wait_for_app_frame_finds_it_immediately_when_already_warm():
    page = _FakePollingPage(frames_appear_after_polls=0)
    frame = ping_deployed_app._wait_for_app_frame(page, total_timeout_ms=10_000)
    assert frame is not None
    assert frame.url == "https://birdzone.streamlit.app/~/+/"


def test_wait_for_app_frame_polls_until_the_frame_shows_up():
    # simulates a real cold start: the iframe doesn't exist for the first few polls
    page = _FakePollingPage(frames_appear_after_polls=3)
    frame = ping_deployed_app._wait_for_app_frame(page, total_timeout_ms=10_000)
    assert frame is not None
    assert page._polls == 3


def test_wait_for_app_frame_gives_up_after_the_timeout_budget():
    # the frame would eventually appear, but not within the budget given - must not
    # poll forever
    page = _FakePollingPage(frames_appear_after_polls=1000)
    frame = ping_deployed_app._wait_for_app_frame(
        page, total_timeout_ms=3 * ping_deployed_app.FRAME_POLL_INTERVAL_MS
    )
    assert frame is None


def test_wake_if_sleeping_clicks_the_button_when_app_is_asleep():
    page = _FakePollingPage(frames_appear_after_polls=0, wake_button_visible=True)
    ping_deployed_app._wake_if_sleeping(page, f=io.StringIO())
    assert page._wake_locator.clicked is True


def test_wake_if_sleeping_does_nothing_when_app_is_already_awake():
    # regression guard: must not raise or click anything when the sleep splash never
    # appears (the normal case - most pings hit an already-awake app)
    page = _FakePollingPage(frames_appear_after_polls=0, wake_button_visible=False)
    ping_deployed_app._wake_if_sleeping(page, f=io.StringIO())
    assert page._wake_locator.clicked is False
