# Benchmarks (synthetic data, Brighter detail + gentle local contrast)

Measured by `tools/benchmark.py`. Hardware: {"cpu": "Intel64 Family 6 Model 198 Stepping 2, GenuineIntel", "cores": 24, "threads": 24, "ram_gb": 68.4, "gpu": "NVIDIA GeForce RTX 5070 Ti", "cc": "12.0", "vram_gb": 17.1, "cupy": "14.2.0", "cuda_runtime": 13020, "driver": 13030, "python": "3.12.10", "platform": "Windows-11-10.0.26300-SP0"}

Cold start (first GPU run, 256x256): 0.70 s - includes CuPy import, CUDA context creation and NVRTC kernel compilation.

| Size | Path | CPU total (s) | CPU pixel group (s) | GPU total (s) | GPU pixel group (s) | GPU transfers (s) | H2D / D2H (MB) | Tile | Decode JPEG (s) | Encode PNG (s) | Peak RAM (MB) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1920x1080 (2.1 MP, Seestar-like) | rendered | 4.24 | 1.98 | 2.37 | 0.12 | 0.019 | 66 / 25 | full | 0.04 | 0.16 | 736 |
| 1920x1080 (2.1 MP, Seestar-like) | linear | 8.68 | 2.75 | 3.44 | 0.19 | 0.037 | 66 / 100 | full | 0.03 | 0.35 | 1156 |
| 2560x1600 (4.1 MP) | rendered | 6.87 | 4.12 | 2.94 | 0.12 | 0.037 | 131 / 49 | full | 0.06 | 0.31 | 1156 |
| 2560x1600 (4.1 MP) | linear | 15.85 | 5.61 | 5.13 | 0.22 | 0.053 | 131 / 197 | full | 0.06 | 0.73 | 1801 |
| 3840x2160 (8.3 MP) | rendered | 12.46 | 8.27 | 4.41 | 0.21 | 0.059 | 265 / 100 | full | 0.10 | 0.73 | 1801 |
| 3840x2160 (8.3 MP) | linear | 28.73 | 10.79 | 8.33 | 0.55 | 0.146 | 265 / 398 | full | 0.10 | 1.58 | 3136 |
| 5120x4096 (21 MP) | rendered | 29.38 | 21.63 | 8.19 | 0.62 | 0.201 | 671 / 252 | full | 0.29 | 1.68 | 3562 |
| 5120x4096 (21 MP) | linear | 74.18 | 29.01 | 18.42 | 1.19 | 0.340 | 671 / 1007 | full | 0.27 | 3.62 | 7169 |

Peak RAM is the process working-set peak so far (sizes run in ascending order).