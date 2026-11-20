import numpy as np

from app.processing.edit_export import Framing, reframe


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
