# EasyAstroEnhance – Copilot instructions

- Follow `astro-photo-enhancer-app-spec.md` and its processing fidelity contract.
- Keep originals immutable and never add celestial content (no generative, learned or reference-image processing).
- Use typed API models and small pure processing functions; `backend/app/processing` must not import FastAPI, SQLite or UI code.
- Preserve precision, channel interpretation, masks, metadata lineage and input-state distinctions. TIFF/FITS never pass through 8-bit.
- Keep main controls simple; hide algorithm parameters in Advanced.
- Write meaningful I/O, numerical and workflow tests; use real images for visual review.
- Record all applied operations and skipped steps; disclose unsupported inputs.
- Include every version 1 control in backend recipes, processing reports and acceptance tests; never ship a decorative slider.
- Keep presets free of per-image regions, masks and fitted models.
- Do not change output algorithms silently; increment `PIPELINE_VERSION` in `backend/app/processing/recipe.py`.
