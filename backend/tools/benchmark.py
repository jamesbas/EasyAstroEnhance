"""CPU vs GPU benchmark on synthetic data of representative sizes (run on the target PC).

    uv run python tools/benchmark.py [--out ../docs/benchmarks.md]

Synthetic images are used only to time the pipeline; quality is compared separately (see tests/unit/test_backends_gpu.py).
Reports cold-start (first GPU run, including CuPy kernel compilation), warm processing, host/device transfer cost,
decode/encode time, total elapsed, peak VRAM (allocator pool) and peak RAM (working set).
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processing.backends import probe_cuda  # noqa: E402
from app.processing.export import write_jpeg, write_png  # noqa: E402
from app.processing.imagedata import ImageData, Normalization  # noqa: E402
from app.processing.pipeline import AssetContext, ExecutionOptions, run_pipeline  # noqa: E402
from app.processing.readers import inspect_file, read_image  # noqa: E402
from app.processing.recipe import Recipe, builtin_presets  # noqa: E402

SIZES = [
    ("1920x1080 (2.1 MP, Seestar-like)", 1080, 1920),
    ("2560x1600 (4.1 MP)", 1600, 2560),
    ("3840x2160 (8.3 MP)", 2160, 3840),
    ("5120x4096 (21 MP)", 4096, 5120),
    ("8192x6144 (50 MP)", 6144, 8192),
]


def make(h, w, domain):
    rng = np.random.default_rng(0)
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    base = 0.08 + 0.15 * np.exp(-(((xx - 0.5) / 0.2) ** 2 + ((yy - 0.5) / 0.1) ** 2))
    img = np.repeat(base[..., None], 3, axis=2) * np.array([1.0, 0.95, 0.85], np.float32)
    n = h * w // 4000
    ys, xs = rng.integers(2, h - 2, n), rng.integers(2, w - 2, n)
    img[ys, xs] += rng.uniform(0.2, 0.9, (n, 1)).astype(np.float32)
    img += rng.normal(0, 0.01, img.shape).astype(np.float32)
    img = np.clip(img, 0, 1).astype(np.float32)
    lin = domain == "linear"
    if lin:
        img = (img * 20000).astype(np.float32)
    return ImageData(
        img, "rgb", "linear" if lin else "display", "x", np.ones((h, w), bool), np.zeros((h, w), bool), {}, "0" * 64, "bench",
        Normalization("unit_range", 255.0), source_format="fits" if lin else "jpeg",
        source_dtype="float32" if lin else "uint8", source_bit_depth=32 if lin else 8,
    )


def timed_run(img, recipe, device, available):
    t0 = time.perf_counter()
    res = run_pipeline(img, recipe, AssetContext(), ExecutionOptions(device=device, gpu_available=available, gpu_threshold_pixels=0))
    total = time.perf_counter() - t0
    group = sum(t["seconds"] for t in res.report["stage_timings"] if t["stage"].startswith("pixel group"))
    return total, group, res.report["execution"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "benchmarks.md"))
    ap.add_argument("--max-mp", type=float, default=60)
    args = ap.parse_args()
    info = probe_cuda()
    gpu = bool(info["ok"])
    recipe = builtin_presets()["vivid"]
    proc = psutil.Process()
    rows, cold = [], None
    for label, h, w in SIZES:
        if h * w / 1e6 > args.max_mp:
            continue
        for domain in ("rendered", "linear"):
            img = make(h, w, domain)
            with tempfile.TemporaryDirectory() as td:
                p = Path(td)
                disp = np.clip(img.pixels if domain == "rendered" else img.pixels / 20000, 0, 1)
                t0 = time.perf_counter()
                write_jpeg(p / "x.jpg", disp)
                enc_jpeg = time.perf_counter() - t0
                t0 = time.perf_counter()
                read_image(p / "x.jpg", "h", 10**9, {}, inspect_file(p / "x.jpg", 10**9))
                dec = time.perf_counter() - t0
                t0 = time.perf_counter()
                write_png(p / "x.png", disp, 8 if domain == "rendered" else 16)
                enc_png = time.perf_counter() - t0
            cpu_runs = [timed_run(img, recipe, "cpu", False) for _ in range(2)]
            row = {
                "size": label, "domain": domain, "mp": h * w / 1e6, "decode_jpeg_s": dec, "encode_jpeg_s": enc_jpeg, "encode_png_s": enc_png,
                "cpu_total_s": statistics.median(r[0] for r in cpu_runs), "cpu_group_s": statistics.median(r[1] for r in cpu_runs),
            }
            if gpu:
                import cupy as cp

                if cold is None:
                    t = timed_run(make(256, 256, "rendered"), recipe, "gpu", True)
                    cold = {"first_gpu_run_total_s": t[0], "note": "includes CuPy import, CUDA context creation and NVRTC kernel compilation"}
                cp.get_default_memory_pool().free_all_blocks()
                runs = [timed_run(img, recipe, "gpu", True) for _ in range(3)]
                ex = runs[-1][2]
                row.update(
                    gpu_total_s=statistics.median(r[0] for r in runs), gpu_group_s=statistics.median(r[1] for r in runs),
                    gpu_transfer_s=ex["transfers"]["seconds"], gpu_h2d_mb=ex["transfers"]["host_to_device_bytes"] / 1e6,
                    gpu_d2h_mb=ex["transfers"]["device_to_host_bytes"] / 1e6, gpu_tile=ex.get("tile"), gpu_actual=ex["actual_backend"],
                    gpu_free_before_mb=info.get("free_memory_bytes", 0) / 1e6,
                )
            row["peak_ram_mb"] = getattr(proc.memory_info(), "peak_wset", proc.memory_info().rss) / 1e6
            rows.append(row)
            print(json.dumps(row), flush=True)
            del img
    hw = {
        "cpu": platform.processor(), "cores": psutil.cpu_count(logical=False), "threads": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "gpu": info.get("device_name"), "cc": info.get("compute_capability"), "vram_gb": round((info.get("total_memory_bytes") or 0) / 1e9, 1),
        "cupy": info.get("cupy_version"), "cuda_runtime": info.get("cuda_runtime_version"), "driver": info.get("cuda_driver_version"),
        "python": sys.version.split()[0], "platform": platform.platform(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Benchmarks (synthetic data, Brighter detail + gentle local contrast)", "", "Measured by `tools/benchmark.py`. Hardware: " + json.dumps(hw), ""]
    if cold:
        lines += [f"Cold start (first GPU run, 256x256): {cold['first_gpu_run_total_s']:.2f} s - {cold['note']}.", ""]
    lines += [
        "| Size | Path | CPU total (s) | CPU pixel group (s) | GPU total (s) | GPU pixel group (s) | GPU transfers (s) | H2D / D2H (MB) | Tile | Decode JPEG (s) | Encode PNG (s) | Peak RAM (MB) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        def f(k, n=2, r=r):
            return "-" if r.get(k) is None else f"{r[k]:.{n}f}"

        lines.append(
            f"| {r['size']} | {r['domain']} | {f('cpu_total_s')} | {f('cpu_group_s')} | {f('gpu_total_s')} | {f('gpu_group_s')} | {f('gpu_transfer_s', 3)} | "
            f"{f('gpu_h2d_mb', 0)} / {f('gpu_d2h_mb', 0)} | {r.get('gpu_tile') or 'full'} | {f('decode_jpeg_s')} | {f('encode_png_s')} | {r['peak_ram_mb']:.0f} |"
        )
    lines += ["", "Peak RAM is the process working-set peak so far (sizes run in ascending order)."]
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
