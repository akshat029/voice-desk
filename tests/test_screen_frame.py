"""Coordinate mapping between screenshot space and screen space.

These cover the two silent accuracy killers: capturing a downscaled image
and then clicking its raw coordinates, and a monitor whose origin is not
(0, 0).
"""

from voicedesk.vision import ScreenFrame


def test_identity_frame_is_a_passthrough():
    frame = ScreenFrame(0, 0, 1920, 1080, 1920, 1080)
    assert frame.to_screen(100, 200) == (100, 200)


def test_downscaled_image_maps_back_up():
    # A 3840x2160 display captured at 1280x720 is a 3x reduction, so a
    # click at (640, 360) in the image is the centre of the screen.
    frame = ScreenFrame(0, 0, 3840, 2160, 1280, 720)
    assert frame.to_screen(640, 360) == (1920, 1080)


def test_secondary_monitor_offset_is_applied():
    # A second monitor to the right of a 1920-wide primary starts at x=1920.
    frame = ScreenFrame(1920, 0, 1920, 1080, 960, 540)
    assert frame.to_screen(0, 0) == (1920, 0)
    assert frame.to_screen(960, 540) == (3840, 1080)


def test_negative_origin_monitor():
    # Monitors placed left of the primary have a negative origin, which is
    # why monitors[0] (the stitched virtual desktop) is unusable for
    # coordinate math.
    frame = ScreenFrame(-1920, 0, 1920, 1080, 1920, 1080)
    assert frame.to_screen(10, 10) == (-1910, 10)


def test_describe_mentions_both_resolutions():
    frame = ScreenFrame(0, 0, 2560, 1440, 1280, 720)
    described = frame.describe()
    assert "1280x720" in described
    assert "2560x1440" in described
