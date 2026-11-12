"""Reader entry points: header-only inspection, intake evaluation and full decoding."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..imagedata import ImageData, ProcessingError
from .common import detect_format, sha256_file
from .fits import inspect_fits, layout_question, read_fits
from .jpeg import inspect_jpeg, read_jpeg
from .tiff import inspect_tiff, read_tiff

__all__ = ["inspect_file", "evaluate_intake", "read_image", "sha256_file", "detect_format"]


def inspect_file(path: Path, max_pixels: int) -> dict[str, Any]:
    """Validate the signature and read headers only (no full decode of large arrays)."""
    fmt = detect_format(path)
    if fmt == "jpeg":
        return inspect_jpeg(path, max_pixels) | {"questions": []}
    if fmt == "tiff":
        return inspect_tiff(path, max_pixels)
    return inspect_fits(path, max_pixels)


def evaluate_intake(inspection: dict[str, Any], interpretation: dict[str, Any]) -> dict[str, Any]:
    """Resolve what is known and what still needs the user.

    Returns status ``ready`` | ``needs_input`` | ``unsupported``; ``can_process`` is False until the
    input state is confirmed (an "I'm not sure" answer allows a labeled preview only).
    """
    fmt = inspection["format"]
    interp = dict(interpretation or {})
    questions: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {"hdu": None, "layout": None, "state": None}
    message = None

    if fmt == "jpeg":
        return {
            "status": "ready", "questions": [], "can_process": True, "can_preview": True,
            "resolved": {"hdu": None, "layout": None, "state": "rendered"}, "message": None,
        }

    if fmt == "fits":
        supported = [c for c in inspection["candidates"] if c["supported"]]
        hdu = interp.get("hdu")
        if hdu is None and len(supported) == 1:
            hdu = supported[0]["index"]
        if hdu is None:
            questions.append(next(q for q in inspection["questions"] if q["id"] == "hdu"))
            cand = supported[0]
        else:
            cand = next((c for c in supported if c["index"] == hdu), supported[0])
            resolved["hdu"] = cand["index"]
        if cand["kind"] in ("rgb_planes", "rgb_last") and not cand["documented"]:
            layout = interp.get("layout")
            if layout == "not_rgb":
                return {
                    "status": "unsupported", "questions": [], "can_process": False, "can_preview": False,
                    "resolved": resolved,
                    "message": "These planes are not color channels, so this looks like a multi-plane cube. "
                    "Export a single stacked RGB or monochrome image and add that instead.",
                    "code": "UNSUPPORTED_CUBE",
                }
            if layout == cand["kind"]:
                resolved["layout"] = layout
            else:
                questions.append(layout_question(cand))
        else:
            resolved["layout"] = cand["kind"]

    state = interp.get("state")
    if state in ("linear", "rendered"):
        resolved["state"] = state
    elif state == "unsure":
        resolved["state"] = "unsure"
        message = (
            "Preview only. A labeled display stretch is shown, but enhancement stays blocked until you confirm "
            "whether this is a linear stack or already processed."
        )
    else:
        questions.append(next(q for q in inspection["questions"] if q["id"] == "state"))

    pending = [q for q in questions]
    status = "ready" if not pending and resolved["state"] in ("linear", "rendered") else "needs_input"
    return {
        "status": status,
        "questions": pending,
        "can_process": status == "ready",
        "can_preview": not any(q["id"] in ("hdu", "layout") for q in pending),
        "resolved": resolved,
        "message": message,
    }


def read_image(
    path: Path,
    source_hash: str,
    max_pixels: int,
    interpretation: dict[str, Any],
    inspection: dict[str, Any],
    preview_only_state: str = "rendered",
) -> ImageData:
    """Fully decode into the canonical ImageData. ``preview_only_state`` is used only for previews of
    assets whose state is unresolved (it never leads to processing)."""
    intake = evaluate_intake(inspection, interpretation)
    if intake["status"] == "unsupported":
        raise ProcessingError(intake.get("code", "UNSUPPORTED"), intake["message"])
    if not intake["can_preview"]:
        raise ProcessingError("NEEDS_INPUT", "Please answer the intake question for this file first.")
    state = intake["resolved"]["state"] or preview_only_state
    fmt = inspection["format"]
    if fmt == "jpeg":
        return read_jpeg(path, source_hash, max_pixels)
    if fmt == "tiff":
        return read_tiff(path, source_hash, max_pixels, state)
    return read_fits(
        path, source_hash, max_pixels, state,
        hdu_index=intake["resolved"]["hdu"], layout=intake["resolved"]["layout"],
    )
