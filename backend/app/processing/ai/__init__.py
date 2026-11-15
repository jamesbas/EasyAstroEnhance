"""Optional AI (learned) processing with third-party ONNX models.

These steps are opt-in per run and fully disclosed: they use trained neural networks that *predict* clean pixels from
the measured ones (image-to-image restoration, no prompts, no reference images, no text-to-image generation). They can
smooth away faint structure or invent texture when pushed, so every run records the model file (name, version,
SHA-256, licence), the execution provider and the strength, and the classical step it replaced.

Models are downloaded on request into the app's data folder (never bundled in the repository).
"""
