# Benchmarks (synthetic data, Vivid preset, engine 1.6.0)

Measured by `tools/benchmark.py`. CPU runs use up to 8 threads (parallel tiles; identical output to one full-frame pass). Hardware: {"cpu": "Intel64 Family 6 Model 198 Stepping 2, GenuineIntel", "cores": 24, "threads": 24, "ram_gb": 68.4, "gpu": "NVIDIA GeForce RTX 5070 Ti", "cc": "12.0", "vram_gb": 17.1, "cupy": "14.2.0", "cuda_runtime": 13020, "driver": 13030, "python": "3.12.10", "platform": "Windows-11-10.0.26300-SP0"}

Cold start (first GPU run, 256x256): 0.27 s - includes CuPy import, CUDA context creation and NVRTC kernel compilation.

| Size | Path | CPU total (s) | CPU pixel group (s) | GPU total (s) | GPU pixel group (s) | GPU transfers (s) | H2D / D2H (MB) | Tile | Decode JPEG (s) | Encode PNG (s) | Peak RAM (MB) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1920x1080 (2.1 MP, Seestar-like) | rendered | 3.79 | 0.82 | 3.26 | 0.28 | 0.259 | 108 / 50 | full | 0.04 | 0.16 | 1182 |
| 1920x1080 (2.1 MP, Seestar-like) | linear | 5.37 | 0.93 | 4.71 | 0.32 | 0.299 | 108 / 75 | full | 0.04 | 0.36 | 1292 |
| 2560x1600 (4.1 MP) | rendered | 5.45 | 1.51 | 4.18 | 0.21 | 0.121 | 213 / 98 | full | 0.07 | 0.34 | 1859 |
| 2560x1600 (4.1 MP) | linear | 8.14 | 1.68 | 6.79 | 0.41 | 0.289 | 213 / 147 | full | 0.06 | 0.70 | 1967 |
| 3840x2160 (8.3 MP) | rendered | 8.23 | 2.87 | 5.78 | 0.46 | 0.234 | 431 / 199 | full | 0.12 | 0.64 | 3119 |
| 3840x2160 (8.3 MP) | linear | 12.57 | 3.17 | 9.97 | 0.59 | 0.394 | 431 / 299 | full | 0.12 | 1.45 | 3342 |
| 5120x4096 (21 MP) | rendered | 19.53 | 9.74 | 10.89 | 1.03 | 0.634 | 1091 / 503 | full | 0.28 | 1.61 | 5873 |
| 5120x4096 (21 MP) | linear | 29.11 | 10.95 | 19.57 | 1.27 | 0.727 | 1091 / 755 | full | 0.29 | 3.57 | 6382 |

Peak RAM is the process working-set peak so far (sizes run in ascending order).
## Engine 1.6 (Phase 2) compared with engine 1.5 after phase 1

Engine 1.6 changes outputs (spec amendment 1.8), so this is a cost comparison, not an identity check. Rendered runs
are unchanged in time. Linear runs add two measured stages that apply when needed: hot/cold pixel repair (about
1.4 s at 8.3 MP, CPU) and the star-fringe check (about 0.9 s at 8.3 MP, CPU); the Vivid preset used here also adds
Star color (0.3), which is part of the existing pixel group.

| Size | Path | CPU 1.5 (s) | CPU 1.6 (s) | GPU 1.5 (s) | GPU 1.6 (s) |
|---|---|---|---|---|---|
| 2.1 MP | rendered | 3.80 | 3.79 | 3.13 | 3.26 |
| 2.1 MP | linear | 4.76 | 5.37 | 4.03 | 4.71 |
| 4.1 MP | rendered | 5.36 | 5.45 | 4.04 | 4.18 |
| 4.1 MP | linear | 7.25 | 8.14 | 5.85 | 6.79 |
| 8.3 MP | rendered | 8.20 | 8.23 | 5.79 | 5.78 |
| 8.3 MP | linear | 11.11 | 12.57 | 8.56 | 9.97 |
| 21 MP | rendered | 19.31 | 19.53 | 10.84 | 10.89 |
| 21 MP | linear | 25.65 | 29.11 | 16.12 | 19.57 |

Iterating is where engine 1.6 saves time: the linear stage is cached per image, so a change of display settings
(Look sliders, tone, colour) reruns only the display stage, identical to a fresh run. On the real Seestar S30 M31
stack (3840 × 2160) a display-only change takes 1.8 s on the GPU and 4.0 s on the CPU instead of a full run, and the
live preview shows it without saving; **Save this result** then publishes the previewed pixels without recomputing.

## Before and after the phase 1 performance work (same engine, same machine)

The "before" column is the unchanged `main` at commit `902810c`, benchmarked from a temporary git worktree on the same
day with the same tool and synthetic inputs. Output pixels and every measured parameter are bit-for-bit identical
(checked on real Seestar M31, M42 LP and JPEG files, CPU and GPU). Only the time changed.

| Size | Path | CPU before (s) | CPU after (s) | GPU before (s) | GPU after (s) |
|---|---|---|---|---|---|
| 2.1 MP | rendered | 8.65 | 3.80 (2.3×) | 5.93 | 3.13 (1.9×) |
| 2.1 MP | linear | 10.57 | 4.76 (2.2×) | 7.55 | 4.03 (1.9×) |
| 4.1 MP | rendered | 13.41 | 5.36 (2.5×) | 7.80 | 4.04 (1.9×) |
| 4.1 MP | linear | 17.28 | 7.25 (2.4×) | 10.95 | 5.85 (1.9×) |
| 8.3 MP | rendered | 21.19 | 8.20 (2.6×) | 10.05 | 5.79 (1.7×) |
| 8.3 MP | linear | 27.14 | 11.11 (2.4×) | 14.55 | 8.56 (1.7×) |
| 21 MP | rendered | 45.88 | 19.31 (2.4×) | 16.80 | 10.84 (1.5×) |
| 21 MP | linear | 59.01 | 25.65 (2.3×) | 26.20 | 16.12 (1.6×) |

On the real Seestar S30 M31 stack (3840 × 2160, Natural): CPU 30.6 s → 13.4 s, GPU 15.3 s → 9.9 s. What changed:
the à trous smoother accumulates in place without padding the whole frame (2.4× faster, identical values); CPU pixel
groups run on 8 threads over tiles whose overlap is the *sum* of the chained filter footprints (the earlier
maximum-footprint overlap left a few seam pixels different by up to 1e-7 when tiling was forced); per-channel sky
statistics, wavelet-noise sample tiles and the decision preview run in parallel; and the global noise estimate overlaps
the gradient and color analysis. On GPU runs the remaining time is mostly single-threaded CPU analysis (star detection,
edge mask, robust statistics), which is the target of the next phase. Run exports are also written in parallel
(not included in these pipeline timings).
