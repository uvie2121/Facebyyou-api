"""Face AI analysis service.

This is the seam where the computer-vision / ML pipeline plugs in. For the MVP
it returns a deterministic, well-structured mock so the full request lifecycle
(upload -> analyze -> persist -> fetch) works end-to-end and the mobile team can
integrate immediately. Replace `_run_inference` with calls to the real models
(on-device handoff, SageMaker endpoint, or local ONNX/Torch runtime) later.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.schemas import (
    AnalysisResult,
    AnalysisStatus,
    MakeupSuggestion,
    SkinMetric,
)

logger = get_logger(__name__)

_DISCLAIMER = (
    "This analysis is an AI-powered wellness screening tool, not a medical "
    "diagnosis. For any health concern, consult a board-certified dermatologist."
)


def _seed_from_key(object_key: str) -> int:
    """Derive a stable pseudo-seed so the same upload yields the same mock result."""
    digest = hashlib.sha256(object_key.encode()).hexdigest()
    return int(digest[:8], 16)


def _run_inference(object_key: str, analysis_types: list[str]) -> dict:
    """Placeholder for the real model pipeline. Deterministic per object_key."""
    seed = _seed_from_key(object_key)

    skin_metrics: list[SkinMetric] = []
    makeup_suggestions: list[MakeupSuggestion] = []
    early_flags: list[str] = []
    skin_age: int | None = None

    if "skin" in analysis_types:
        names = ["hydration", "oiliness", "texture", "pore_size", "redness", "dark_spots"]
        skin_metrics = [
            SkinMetric(name=name, score=float((seed >> (i * 3)) % 101))
            for i, name in enumerate(names)
        ]
        skin_age = 20 + (seed % 30)

    if "makeup" in analysis_types:
        makeup_suggestions = [
            MakeupSuggestion(
                product_type="foundation",
                shade=f"warm-{seed % 10}",
                hex_color="#D8A07A",
                reason="Matched to detected undertone and lighting.",
            ),
            MakeupSuggestion(
                product_type="blush",
                shade="soft-rose",
                hex_color="#E59A9A",
                reason="Complements estimated skin tone.",
            ),
        ]

    if "early_detection" in analysis_types and seed % 7 == 0:
        early_flags = ["asymmetric_mole_detected"]

    return {
        "skin_metrics": skin_metrics,
        "makeup_suggestions": makeup_suggestions,
        "early_detection_flags": early_flags,
        "skin_age_estimate": skin_age,
    }


def analyze(
    *, user_id: str, object_key: str, analysis_types: list[str]
) -> AnalysisResult:
    """Run the face analysis pipeline and return a structured result."""
    logger.info(
        "Running face analysis",
        extra={"user_id": user_id, "object_key": object_key, "types": analysis_types},
    )
    inference = _run_inference(object_key, analysis_types)
    return AnalysisResult(
        analysis_id=uuid.uuid4().hex,
        user_id=user_id,
        object_key=object_key,
        status=AnalysisStatus.completed,
        disclaimer=_DISCLAIMER,
        created_at=datetime.now(UTC),
        **inference,
    )
