import numpy as np
import pytest

from app.processing.edit_export import FONT_FILES, Caption, Framing, TextStyle, _draw_captions, caption_font, reframe
from app.processing.imagedata import ProcessingError


def test_quarter_turn_and_edge_crop_preserve_exact_16_bit_pixels():
    source = np.arange(60, dtype=np.uint16).reshape((6, 10)) + 891
    rotated = reframe(source, Framing(90, 1, 0, 0))
    expected = source[::-1].T
    np.testing.assert_array_equal(rotated, expected)
    # At maximum right / minimum top, retain the top-right quarter of the rotated image.
    np.testing.assert_array_equal(reframe(source, Framing(90, 2, 1, -1)), expected[:5, -3:])


def test_fine_rotation_maps_right_of_center_down_and_keeps_canvas_bounded():
    source = np.zeros((101, 101, 3), dtype=np.uint16)
    source[49:52, 74:77, 0] = 12345
    result = reframe(source, Framing(30, 1, 0, 0))
    assert result.dtype == np.uint16 and result.shape == source.shape
    peak_y, peak_x = np.unravel_index(result[..., 0].argmax(), result.shape[:2])
    np.testing.assert_allclose((peak_y, peak_x), (59, 66), atol=2)
    assert 11000 < result[..., 0].max() <= 12345 and not result[..., 1:].any()
    assert not result[0, 0].any()


def test_preview_is_capped_without_changing_the_framing():
    source = np.full((300, 600), 2468, dtype=np.uint16)
    source[:, :300] = 7234
    frame = Framing(0, 2, -1, 0)
    preview = reframe(source, frame, max_edge=100)
    full = reframe(source, frame)
    assert preview.shape == (50, 100) and full.shape == (150, 300)
    assert np.all(preview == 7234) and np.all(full == 7234)


def _changed(before: np.ndarray, after: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(np.any(before != after, axis=-1) if before.ndim == 3 else before != after)
    return ys.min(), ys.max(), xs.min(), xs.max()


@pytest.mark.parametrize("position", ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"])
def test_caption_lands_at_the_chosen_position(position):
    image = np.full((300, 400, 3), 20000, dtype=np.uint16)
    out = image.copy()
    _draw_captions(out, [Caption("M 101", position, 1.0)])
    y0, y1, x0, x1 = _changed(image, out)
    vertical, horizontal = position.split("-")
    assert (y1 < 100) if vertical == "top" else (y0 > 200)
    centre = (x0 + x1) / 2
    assert {"left": centre < 130, "center": 150 < centre < 250, "right": centre > 270}[horizontal]


def test_caption_colour_box_size_and_separate_placement():
    image = np.full((300, 400, 3), 30000, dtype=np.uint16)
    boxed = image.copy()
    _draw_captions(boxed, [Caption("M 31", "top-left"), Caption("Jaime", "bottom-right", 0.6)], TextStyle("serif", (255, 0, 0), True))
    top, bottom = boxed[:150], boxed[150:]
    assert (top[..., 0] == 65535).any() and not (top[..., 1] > 30000).any()  # red text, no green: colour is applied
    assert (top == np.array([10500, 10500, 10500])).all(axis=-1).any()  # the dark box (35 % of the background)
    assert (bottom != 30000).any()
    big, small = _changed(image[:150], top), _changed(image[150:], bottom)
    assert (big[1] - big[0]) > (small[1] - small[0])  # the smaller size draws a lower block
    plain = image.copy()
    _draw_captions(plain, [Caption("M 31", "top-left")], TextStyle("sans", (255, 255, 255), False))
    changed = np.any(plain != image, axis=-1)
    assert (plain[changed] < 30000).any() and (plain[changed] == 65535).any()  # dark outline around white text, no box
    assert changed.sum() < np.any(boxed[:150] != image[:150], axis=-1).sum()


def test_captions_keep_clear_of_compass_and_scale_bar():
    image = np.zeros((300, 400), dtype=np.uint16)
    out = image.copy()
    compass = (300, 0, 400, 90)
    _draw_captions(out, [Caption("North up", "top-right")], avoid=[compass])
    y0, _, _, _ = _changed(image, out)
    assert y0 >= 90


def test_every_caption_font_has_accented_letters():
    for name in FONT_FILES:
        font = caption_font(name, 40)
        missing = np.asarray(font.getmask("\U000F0000"))
        for ch in "éñüł©°":
            mask = np.asarray(font.getmask(ch))
            assert not (mask.shape == missing.shape and (mask == missing).all()), (name, ch)


def test_text_that_cannot_fit_is_refused():
    with pytest.raises(ProcessingError) as err:
        _draw_captions(np.zeros((20, 30), dtype=np.uint16), [Caption("A very long caption that cannot fit", "bottom-left", 3)])
    assert err.value.code == "CAPTION_TOO_LARGE"
