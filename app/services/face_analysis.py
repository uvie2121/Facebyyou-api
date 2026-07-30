"""Face AI analysis service.

Orchestrates the analysis pipeline by delegating processing to the VisionEngine
and persisting results according to the Database Design specification.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import (
    AIFeedback,
    AnalysisResult,
    AnalysisStatus,
    CategoryScores,
    LightingCondition,
)
from app.services.database import get_last_user_feedback, update_user_score_stats
from app.services.feedback_engine import NvidiaFeedbackService
from app.services.image_validation import validate_image
from app.services.storage import create_presigned_read_url, object_exists
from app.services.vision_engine import VisionEngine

logger = get_logger(__name__)

# Initialize the VisionEngine once at module level to keep the model warm
engine = VisionEngine()
feedback_engine = NvidiaFeedbackService()


def fetch_image_from_s3(object_key: str) -> np.ndarray:
    """Downloads S3 bytes directly to memory for the CV engine."""

    # --- THIS BLOCK FOR LOCAL TESTING ---
    # Check if the file exists locally (either by full key path or directly in root)
    filename = os.path.basename(object_key)
    local_path_full = os.path.join(os.getcwd(), object_key)
    local_path_root = os.path.join(os.getcwd(), filename)

    if os.path.exists(local_path_full):
        logger.info(f"Loading local test image from path: {local_path_full}")
        return cv2.imread(local_path_full)
    elif os.path.exists(local_path_root):
        logger.info(f"Loading local test image from root: {local_path_root}")
        return cv2.imread(local_path_root)
    # ----------------------------------------

    # Defensive Check: Verify existence before attempting download

    if not object_exists(object_key):
        logger.error(f"S3 Object not found: {object_key}")

        raise ValueError("Image could not be retrieved from storage.")

    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=settings.S3_UPLOAD_BUCKET, Key=object_key)
    image_data = response["Body"].read()

    # Convert raw bytes to a numpy array, then decode into an OpenCV image
    nparr = np.frombuffer(image_data, np.uint8)
    image_array = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    return image_array


def get_image_url_or_base64(object_key: str) -> str:
    """
    In dev/testing: If the image exists locally on disk, convert to Base64 data URI.
    In prod: Generate a pre-signed S3 GET URL.
    """
    filename = os.path.basename(object_key)
    cwd_path = os.path.join(os.getcwd(), filename)
    rel_path = os.path.join(os.getcwd(), object_key)
    project_root = Path(__file__).resolve().parents[2]
    root_path = os.path.join(project_root, filename)

    # If local file exists, encode it as Base64 so NIM can inspect it without S3
    for candidate_path in [rel_path, cwd_path, root_path]:
        if os.path.exists(candidate_path):
            with open(candidate_path, "rb") as img_file:
                encoded = base64.b64encode(img_file.read()).decode("utf-8")
                ext = os.path.splitext(candidate_path)[1].lower()
                mime = "image/png" if ext == ".png" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"

    return create_presigned_read_url(object_key)


def assess_lighting(image_bgr: np.ndarray) -> LightingCondition:
    """
    Evaluates raw pixel variance to detect extreme lighting conditions.
    Returns: 'harsh_flash', 'too_dark', or 'balanced'
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    std_dev = np.std(gray)
    mean_brightness = np.mean(gray)

    # High variance + High brightness usually means a camera flash or direct sunlight
    if std_dev > 70 and mean_brightness > 140:
        return LightingCondition.HARSH_FLASH
    elif mean_brightness < 60:
        return LightingCondition.TOO_DARK

    return LightingCondition.BALANCED


def apply_clahe_normalization(image_bgr: np.ndarray) -> np.ndarray:
    """
    Flattens extreme highlights and shadows using Contrast Limited Adaptive Histogram Equalization.
    """
    # Convert to LAB color space to safely adjust lightness without distorting skin tones
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)

    # Apply CLAHE to the L (Lightness) channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(lightness)

    # Merge channels back together and convert back to BGR
    merged_lab = cv2.merge((cl, a, b))
    flattened_bgr = cv2.cvtColor(merged_lab, cv2.COLOR_LAB2BGR)

    return flattened_bgr


def _process_single_view(object_key: str, view: str) -> dict:
    """Synchronous helper to fetch and process a single image."""
    try:
        # fetch image
        image_array = fetch_image_from_s3(object_key)

        if image_array is None or image_array.size == 0:
            return {"success": False, "error": "Corrupt image data."}

        # image Validation Check ---
        validation_result = validate_image(image_array, view)
        if not validation_result["valid"]:
            # If invalid, join the errors into a single string and fail early
            error_message = " | ".join(validation_result["errors"])
            logger.warning(f"Validation failed for {view}: {error_message}")
            return {"success": False, "error": error_message}

        # Assess lighting on the RAW, un-normalized image
        lighting_cond = assess_lighting(image_array)
        logger.info(f"Assessed lighting for {view} view: {lighting_cond}")

        # Apply CLAHE normalization to flatten harsh highlights/shadows
        if lighting_cond != LightingCondition.BALANCED:
            final_image_for_scoring = apply_clahe_normalization(image_array)
            logger.info(f"Applied CLAHE normalization for {view} view.")
        else:
            final_image_for_scoring = image_array

        # Pass the NORMALIZED image to the vision engine for scoring
        analysis_result = engine.analyze_face(final_image_for_scoring, view=view)

        # Inject the assessed lighting condition into the result payload
        if isinstance(analysis_result, dict) and analysis_result.get("success", True):
            analysis_result["lighting_condition"] = lighting_cond

        return analysis_result

    except Exception as e:
        logger.error(f"Failed to process {view} view: {e}")
        return {"success": False, "error": str(e)}


async def analyze(
    *,
    user_id: str,
    session_id: str,
    front_key: str,
    left_key: str,
    right_key: str,
    analysis_types: list[str],
) -> AnalysisResult:
    """Run the Tri-Angle AI pipeline concurrently, aggregate scores, and return results."""
    logger.info("Running concurrent Tri-Angle face analysis", extra={"user_id": user_id})

    # Dispatch the 3 blocking tasks to background worker threads
    front_task = asyncio.to_thread(_process_single_view, front_key, "front")
    left_task = asyncio.to_thread(_process_single_view, left_key, "left")
    right_task = asyncio.to_thread(_process_single_view, right_key, "right")

    # Await all three tasks simultaneously
    front_data, left_data, right_data = await asyncio.gather(front_task, left_task, right_task)

    # Strict Defensive check on ALL images
    if not front_data.get("success"):
        raise ValueError(f"Front image analysis failed: {front_data.get('error')}")
    if not left_data.get("success"):
        raise ValueError(f"Left image analysis failed: {left_data.get('error')}")
    if not right_data.get("success"):
        raise ValueError(f"Right image analysis failed: {right_data.get('error')}")

    # Extract metrics (Strict validation above guarantees these exist)
    f_metrics = front_data["metrics"]
    l_metrics = left_data["metrics"]
    r_metrics = right_data["metrics"]

    # Tri-Angle Aggregation Math using scores generated on CLAHE-flattened images
    foundation_avg = (
        f_metrics["foundation_score"]
        + l_metrics["foundation_score"]
        + r_metrics["foundation_score"]
    ) / 3
    contour_avg = (
        f_metrics["contour_score"] + l_metrics["contour_score"] + r_metrics["contour_score"]
    ) / 3
    blend_avg = (f_metrics["blend_score"] + l_metrics["blend_score"] + r_metrics["blend_score"]) / 3

    # Calculate final Overall Score
    overall = (
        (foundation_avg * 0.15)
        + (blend_avg * 0.15)
        + (contour_avg * 0.10)
        + (f_metrics["eyes_score"] * 0.20)
        + (f_metrics["lips_score"] * 0.10)
        + (f_metrics["symmetry_score"] * 0.15)
        + (f_metrics["base_finish_score"] * 0.10)
        + (f_metrics["color_balance_score"] * 0.05)
    )

    # Map to the database schema
    aggregated_scores = {
        "foundation_score": round(foundation_avg, 2),
        "blend_score": round(blend_avg, 2),
        "contour_score": round(contour_avg, 2),
        "eyes_score": f_metrics["eyes_score"],
        "lips_score": f_metrics["lips_score"],
        "symmetry_score": f_metrics["symmetry_score"],
        "base_finish_score": f_metrics["base_finish_score"],
        "color_balance_score": f_metrics["color_balance_score"],
        "overall_score": round(overall, 2),
    }

    # deterministic score engine separated from the generative feedback call.
    front_lighting = front_data.get("lighting_condition", LightingCondition.BALANCED)

    last_feedback = await asyncio.to_thread(get_last_user_feedback, user_id)

    vision_output_payload = {
        "image_urls": {
            "front": get_image_url_or_base64(front_key),
            "left": get_image_url_or_base64(left_key),
            "right": get_image_url_or_base64(right_key),
        },
        "analysis_results": aggregated_scores,
    }

    ai_feedback_data = await asyncio.to_thread(
        feedback_engine.generate_feedback,
        vision_output_payload,
        front_lighting,
        last_feedback,
    )


    try:
        await asyncio.to_thread(update_user_score_stats, user_id, overall)
    except Exception as db_err:
        logger.warning("User score statistics update failed", extra={"error": str(db_err)})

    return AnalysisResult(
        analysis_id=uuid.uuid4().hex,
        session_id=session_id,
        user_id=user_id,
        # object_key=front_key, # Link the DB record to the primary front image
        status=AnalysisStatus.completed,
        disclaimer="This analysis is an AI-powered makeup scoring tool.",
        created_at=datetime.now(UTC),
        category_scores=CategoryScores(**aggregated_scores),
        ai_feedback=AIFeedback(
            glam_type=ai_feedback_data.get("glam_type", "N/A"),
            strengths=ai_feedback_data.get("strengths", []),
            improvements=ai_feedback_data.get("improvements", []),
            recommendations=ai_feedback_data.get("recommendations", []),
        ),
        confidence_score=f_metrics["confidence_score"],
    )
