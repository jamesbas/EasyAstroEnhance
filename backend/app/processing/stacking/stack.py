"""Stacking entry points: plan (scan + summary for the UI) and run (calibrate, register, integrate, write FITS)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ..imagedata import ProcessingError
from .calibrate import build_calibration
from .frames import FrameInfo, choose_lights, scan_folder, summarize
from .integrate import StackOptions, stack_sessions, stack_subs, write_stack_fits

STACK_VERSION = "1.0.0"
CAL_KINDS = {"darks": "dark", "flats": "flat", "bias": "bias", "darkflats": "darkflat"}


@dataclass
class StackRequest:
    folder: str
    mode: str = "auto"  # auto | subs | sessions
    darks: str | None = None
    flats: str | None = None
    bias: str | None = None
    darkflats: str | None = None
    scale: int = 1
    grading: str = "standard"
    rejection: str = "sigma"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _collect(req: StackRequest) -> tuple[dict[str, list[FrameInfo]], list[dict[str, str]], dict[str, str]]:
    main = scan_folder(req.folder)
    groups: dict[str, list[FrameInfo]] = {k: main.by_kind(k) for k in ("light", "dark", "flat", "bias", "darkflat")}
    skipped = list(main.skipped)
    sources = {k: req.folder for k in groups if groups[k]}
    for field, kind in CAL_KINDS.items():
        folder = getattr(req, field)
        if not folder:
            continue
        extra = scan_folder(folder, force_kind=kind)
        groups[kind] = extra.frames  # an explicit folder replaces same-kind frames found next to the lights
        sources[kind] = folder
        skipped += [{"name": f"{Path(folder).name}/{s['name']}", "reason": s["reason"]} for s in extra.skipped]
    return groups, skipped, sources


def plan(req: StackRequest) -> dict[str, Any]:
    groups, skipped, sources = _collect(req)
    mode, chosen = choose_lights(groups["light"], req.mode)
    lights = chosen.frames
    out: dict[str, Any] = {
        "mode": mode, "lights": summarize(lights), "excluded": chosen.excluded, "skipped": skipped,
        "calibration": {k: len(groups[k]) for k in ("dark", "flat", "bias", "darkflat")} if mode == "subs" else None,
        "sources": sources, "warnings": [], "can_stack": len(lights) >= 2, "drizzle_available": mode == "subs",
    }
    if mode == "sessions" and any(groups[k] for k in ("dark", "flat", "bias", "darkflat")):
        out["warnings"].append("Calibration frames are ignored when combining already-stacked images.")
    if len(lights) < 2:
        out["warnings"].append("At least two light frames are needed to stack." if lights or not groups["light"] else "")
    if lights:
        w, h = lights[0].width, lights[0].height
        out["output"] = {"native": [w, h], "drizzle2x": [2 * w, 2 * h] if mode == "subs" else None}
        if mode == "subs" and len(lights) > 1 and len({f.exposure for f in lights}) > 1:
            out["warnings"].append("Sub-frames have different exposure times; they are normalized and weighted by noise.")
    out["warnings"] = [w for w in out["warnings"] if w]
    return out


def run_stack(req: StackRequest, out_path: Path, check: Callable[[], None], progress: Callable[[str, float], None],
              device: str = "auto", threads: int = 4, memory_budget_bytes: int = 3 * 1024**3) -> dict[str, Any]:
    groups, skipped, sources = _collect(req)
    mode, chosen = choose_lights(groups["light"], req.mode)
    lights = chosen.frames
    if len(lights) < 2:
        raise ProcessingError("TOO_FEW_FRAMES", "At least two light frames are needed to stack.")
    if req.scale not in (1, 2):
        raise ProcessingError("BAD_SCALE", "Output size must be native (1x) or 2x drizzle.")
    opts = StackOptions(mode=mode, scale=req.scale if mode == "subs" else 1, grading=req.grading, rejection=req.rejection,
                        device=device, threads=threads, memory_budget_bytes=memory_budget_bytes)
    if mode == "subs":
        progress("Preparing calibration", 0.0)
        cal = build_calibration(lights, groups["dark"], groups["flat"], groups["bias"], groups["darkflat"], check,
                                lambda msg: progress(msg, 0.0))
        result = stack_subs(lights, cal, opts, check, progress)
    else:
        result = stack_sessions(lights, opts, check, progress)
    rep = result.report
    rep.update({"stack_version": STACK_VERSION, "request": req.to_dict(), "sources": sources, "excluded": chosen.excluded,
                "skipped": skipped, "lights": summarize(lights), "output": {"width": int(result.data.shape[1]), "height": int(result.data.shape[0])}})
    progress("Writing stacked image", 0.99)
    history = [f"EasyAstroEnhance stack {STACK_VERSION}: {rep['mode']}, {rep['frames_used']}/{rep['frames_total']} frames",
               f"Registration/integration: {rep.get('integration', {}).get('method', '')}"]
    if rep.get("calibration"):
        c = rep["calibration"]
        history.append(f"Calibration: darks {c['darks']}, flats {c['flats']}, bias {c['bias']}, dark-flats {c['dark_flats']}")
    write_stack_fits(out_path, result, history)
    return rep
