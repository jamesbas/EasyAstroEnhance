# Benchmarks (synthetic data, Vivid preset, engine 1.7.0)

Measured by `tools/benchmark.py`. CPU runs use up to 8 threads (parallel tiles; identical output to one full-frame pass). Hardware: {"cpu": "Intel64 Family 6 Model 198 Stepping 2, GenuineIntel", "cores": 24, "threads": 24, "ram_gb": 68.4, "gpu": "NVIDIA GeForce RTX 5070 Ti", "cc": "12.0", "vram_gb": 17.1, "cupy": "14.2.0", "cuda_runtime": 13020, "driver": 13030, "python": "3.12.10", "platform": "Windows-11-10.0.26300-SP0"}

Cold start (first GPU run, 256x256): 0.25 s - includes CuPy import, CUDA context creation and NVRTC kernel compilation.

| Size | Path | CPU total (s) | CPU pixel group (s) | GPU total (s) | GPU pixel group (s) | GPU transfers (s) | H2D / D2H (MB) | Tile | Decode JPEG (s) | Encode PNG (s) | Peak RAM (MB) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1920x1080 (2.1 MP, Seestar-like) | rendered | 3.84 | 0.80 | 3.25 | 0.24 | 0.189 | 116 / 50 | full | 0.04 | 0.16 | 1188 |
| 1920x1080 (2.1 MP, Seestar-like) | linear | 5.77 | 0.90 | 5.20 | 0.33 | 0.279 | 116 / 75 | full | 0.04 | 0.35 | 1301 |
| 2560x1600 (4.1 MP) | rendered | 5.48 | 1.47 | 4.25 | 0.21 | 0.125 | 229 / 98 | full | 0.07 | 0.32 | 1849 |
| 2560x1600 (4.1 MP) | linear | 8.75 | 1.67 | 7.48 | 0.43 | 0.214 | 229 / 147 | full | 0.06 | 0.69 | 1957 |
| 3840x2160 (8.3 MP) | rendered | 8.48 | 2.84 | 6.12 | 0.48 | 0.293 | 464 / 199 | full | 0.12 | 0.63 | 3136 |
| 3840x2160 (8.3 MP) | linear | 13.82 | 3.24 | 11.21 | 0.61 | 0.391 | 464 / 299 | full | 0.12 | 1.41 | 3337 |
| 5120x4096 (21 MP) | rendered | 20.05 | 9.82 | 11.41 | 1.10 | 0.641 | 1174 / 503 | full | 0.31 | 1.60 | 5887 |
| 5120x4096 (21 MP) | linear | 32.03 | 10.92 | 22.20 | 1.33 | 0.737 | 1174 / 755 | full | 0.30 | 3.61 | 6431 |
| 8192x6144 (50 MP) | rendered | 42.45 | 17.86 | 27.73 | 3.06 | 1.818 | 2962 / 1208 | 5952 | 0.63 | 3.91 | 15089 |
| 8192x6144 (50 MP) | linear | 65.58 | 20.19 | 49.50 | 3.56 | 2.099 | 2962 / 1812 | 5952 | 0.62 | 9.65 | 16417 |

Peak RAM is the process working-set peak so far (sizes run in ascending order).

## Engine 1.7 (Phase 3) compared with engine 1.6

Engine 1.7 changes outputs (spec amendments 1.7 and 1.9). With every optional tool off, rendered runs are unchanged in
time; linear runs add the always-on row/column banding measurement and, with the Vivid preset used here (Contrast 0.5),
the large-scale structure band — about 1.2 s at 8.3 MP on either device. The optional tools cost extra only when
switched on (measured on the real 8.3 MP M31 stack): sky solving 1.9–2.5 s per image (once; stored with the image),
Accurate star colours 0.9 s, AI sharpening ≈ 12 s on the RTX 5070 Ti (DirectML), Star size 1.1 s; layer exports are
made only when downloaded. The banding check itself is 0.9 s of the linear-run increase.

| Size | Path | CPU 1.6 (s) | CPU 1.7 (s) | GPU 1.6 (s) | GPU 1.7 (s) |
|---|---|---|---|---|---|
| 2.1 MP | rendered | 3.79 | 3.84 | 3.26 | 3.25 |
| 2.1 MP | linear | 5.37 | 5.77 | 4.71 | 5.20 |
| 4.1 MP | rendered | 5.45 | 5.48 | 4.18 | 4.25 |
| 4.1 MP | linear | 8.14 | 8.75 | 6.79 | 7.48 |
| 8.3 MP | rendered | 8.23 | 8.48 | 5.78 | 6.12 |
| 8.3 MP | linear | 12.57 | 13.82 | 9.97 | 11.21 |
| 21 MP | rendered | 19.53 | 20.05 | 10.89 | 11.41 |
| 21 MP | linear | 29.11 | 32.03 | 19.57 | 22.20 |

Stacking (real Seestar data, target PC): NGC 7000 mosaic, 6 subs → 1337 × 2150 in 5 s; IC 1805 mosaic, 84 subs (41
panels) → 2713 × 3113 in 50 s; lunar RAW video, 1495 frames (536 × 960) → 374 frames used in 26 s; Jupiter RAW video,
1581 frames (264 × 480) → 395 used in 5 s.

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
