import os
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from app.core.logging import get_logger

logger = get_logger(__name__)

# Initialize the FaceLandmarker
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "face_landmarker.task")

base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    num_faces=2,  # Catch multiple faces
    min_face_detection_confidence=0.6,
    min_face_presence_confidence=0.6,
)

# Initialize globally to keep it warm in memory
detector = vision.FaceLandmarker.create_from_options(options)


def validate_image(image_array: np.ndarray, view: str) -> dict[str, Any]:
    """
    Validates an image using the MediaPipe Tasks API.
    """
    errors = []

    if image_array is None or image_array.size == 0:
        return {"success": False, "valid": False, "errors": ["Image could not be read."]}

    # 1. Lighting & Blur Checks
    gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
    brightness = np.mean(gray)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

    height, width = image_array.shape[:2]
    # blur_score = raw_blur_score / (height * width)

    if brightness < 40:
        errors.append("Image is too dark.")
    elif brightness > 240:
        errors.append("Image is too bright.")

    if blur_score < 100:
        errors.append("Image is too blurry.")

    # Convert to the mp.Image format required by Tasks API
    rgb_img = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)

    # Run Inference
    detection_result = detector.detect(mp_image)

    pose_ratio = None

    # The API returns a list of faces under 'face_landmarks'
    if not detection_result.face_landmarks:
        errors.append("No face detected.")
    elif len(detection_result.face_landmarks) > 1:
        errors.append("Multiple faces detected.")
    else:
        # Pose Validation
        landmarks = detection_result.face_landmarks[0]

        nose = landmarks[1]
        left_ear = landmarks[234]
        right_ear = landmarks[454]

        dist_left = abs(nose.x - left_ear.x)
        dist_right = abs(nose.x - right_ear.x)

        dist_right = max(dist_right, 0.001)
        pose_ratio = dist_left / dist_right

        if view == "front" and (pose_ratio < 0.5 or pose_ratio > 2.0):
            errors.append("Face is not looking straight at the camera.")
        elif view == "left" and pose_ratio < 1.4: #relaxed from 2.0
            errors.append("Face does not appear to be a correct left profile.")
        elif view == "right" and pose_ratio > 0.7: #relaxed from 0.5
            errors.append("Face does not appear to be a correct right profile.")

    is_valid = len(errors) == 0

    if not is_valid:
        logger.warning(f"Validation failed for '{view}'. Errors: {errors}")

    return {
        "success": is_valid,
        "valid": is_valid,
        "errors": errors,
        "metrics": {
            "blur_score": round(float(blur_score), 2),
            "brightness_score": round(float(brightness), 2),
            "pose_ratio": round(float(pose_ratio), 2) if pose_ratio else None,
        },
    }
