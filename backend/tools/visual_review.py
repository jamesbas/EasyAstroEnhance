"""Visual-review helper: runs Natural and Brighter detail on every file in samplepics/ and writes, per file/preset,
a full-frame comparison JPEG, matched 100% crops (bright region, dark sky, brightest star, bottom label area)
and the processing report to docs/visual-review/ (git-ignored; never committed).

    uv run python tools/visual_review.py [--with-local-contrast]

Aesthetic acceptance is the user's judgment; this only makes the review reproducible.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processing.diagnostics import luminance_np  # noqa: E402
from app.processing.export import comparison_jpeg, to_u8  # noqa: E402
from app.processing.imagedata import ProcessingError  # noqa: E402
from app.processing.pipeline import AssetContext, ExecutionOptions, prepare_linear_frame, run_pipeline  # noqa: E402
from app.processing.readers import evaluate_intake, inspect_file, read_image, sha256_file  # noqa: E402
from app.processing.recipe import builtin_presets  # noqa: E402
from scipy import ndimage  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def pick_crops(base: np.ndarray, size: int = 160) -> dict[str, tuple[int, int]]:
    L = luminance_np(base)
    h, w = L.shape
    sm = ndimage.uniform_filter(L, size)
    crops: dict[str, tuple[int, int]] = {}
    clamp = lambda y, x: (int(np.clip(y - size // 2, 0, h - size)), int(np.clip(x - size // 2, 0, w - size)))  # noqa: E731
    crops["bright region"] = clamp(*np.unravel_index(np.argmax(sm), sm.shape))
    margin = size // 2
    inner = sm[margin : h - margin, margin : w - margin]
    crops["dark sky"] = clamp(*(np.array(np.unravel_index(np.argmin(inner), inner.shape)) + margin))
    gl = ndimage.gaussian_filter(L, 2)
    crops["bright star"] = clamp(*np.unravel_index(np.argmax(gl), gl.shape))
    crops["bottom-left label area"] = (h - size, 0)
    return crops


def crop_sheet(base, enh, crops, size=160, zoom=2) -> Image.Image:
    tiles = []
    for name, (y, x) in crops.items():
        a = to_u8(base)[y : y + size, x : x + size]
        b = to_u8(enh)[y : y + size, x : x + size]
        pair = Image.fromarray(np.hstack([a, np.full((size, 4) + a.shape[2:], 30, np.uint8), b])).resize(((2 * size + 4) * zoom, size * zoom), Image.NEAREST).convert("RGB")
        d = ImageDraw.Draw(pair)
        d.text((4, 4), f"{name}  (left: original, right: enhanced)", fill=(255, 255, 0))
        tiles.append(np.asarray(pair.convert("RGB")))
    return Image.fromarray(np.vstack(tiles))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-local-contrast", action="store_true")
    args = ap.parse_args()
    out_root = ROOT / "docs" / "visual-review"
    for path in sorted((ROOT / "samplepics").glob("*")):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".tif", ".tiff", ".fit", ".fits", ".fts"):
            continue
        try:
            insp = inspect_file(path, 10**9)
        except ProcessingError as exc:
            print(f"skip {path.name}: {exc.message}")
            continue
        interp = {"state": "linear"} if insp["format"] != "jpeg" else {}
        if evaluate_intake(insp, interp)["status"] != "ready":
            print(f"skip {path.name}: needs interpretation")
            continue
        img = read_image(path, sha256_file(path), 10**9, interp, insp)
        frame = prepare_linear_frame(img).to_dict() if img.domain == "linear" else None
        for pid, recipe in builtin_presets().items():
            if args.with_local_contrast:
                recipe = recipe.model_copy(update={"local_contrast": recipe.local_contrast.model_copy(update={"enabled": True})})
            res = run_pipeline(img, recipe, AssetContext(frame=frame), ExecutionOptions(device="cpu"))
            d = out_root / path.stem[:40].replace(" ", "_") / pid
            d.mkdir(parents=True, exist_ok=True)
            left = "Original view" if img.domain == "display" else "Original shown with a display stretch"
            comparison_jpeg(d / "comparison.jpg", res.baseline, res.display, left, "Enhanced", 1800)
            crop_sheet(res.baseline, res.display, pick_crops(res.baseline)).save(d / "crops-100pct.png")
            (d / "processing-summary.json").write_text(json.dumps({"summary": res.summary, "operations": res.report["operations"], "clipping": res.report["clipping"]}, indent=2, default=str))
            print(f"{path.name} / {pid}: {res.summary}")
    print("written to", out_root)


if __name__ == "__main__":
    main()
