import os

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class VisionEngine:
    def __init__(self, model_path: str = "face_landmarker.task"):
        """Initialize the modern MediaPipe Tasks API Face Landmarker."""

        # Defensive check for the physical model file
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model file '{model_path}' not found. "
                "Ensure you have downloaded face_landmarker.task into your project root."
            )

        base_options = python.BaseOptions(model_asset_path=model_path)

        # Configure the options schema
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)

    def analyze_face(self, image: np.ndarray, view: str = "front") -> dict:
        """
        Processes an in-memory OpenCV image, extracts landmarks using the Tasks API,
        and returns standardized geometric and color metrics.
        """
        if image is None or image.size == 0:
            return {"success": False, "error": "Invalid image data provided."}

        # 1. Convert BGR (OpenCV default) to RGB
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # 2. Convert to the specific mp.Image object required by the Tasks API
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

        # 3. Process with Face Landmarker
        detection_result = self.landmarker.detect(mp_image)

        if not detection_result.face_landmarks:
            return {"success": False, "error": "No face detected in image."}

        # Extract the landmarks list for the first detected face
        landmarks = detection_result.face_landmarks[0]

        # Route to the correct geometric math based on the view
        if view == "front":
            metrics = self._calculate_front_metrics(image, landmarks)
        else:
            metrics = self._calculate_profile_metrics(image, landmarks, view)

        metrics["confidence_score"] = 95.0
        return {"success": True, "metrics": metrics}

    def _calculate_foundation_score(self, image: np.ndarray, landmarks) -> float:
        """Calculates foundation evenness using LAB color space variance."""
        h, w, _ = image.shape
        lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)

        # Sample points: Forehead (10), Left Cheek (234), Right Cheek (454), Chin (152)
        points = [10, 234, 454, 152]
        samples = []

        for idx in points:
            lm = landmarks[idx]
            x = max(0, min(int(lm.x * w), w - 1))
            y = max(0, min(int(lm.y * h), h - 1))
            samples.append(lab_image[y, x])

        # Calculate color variance
        samples = np.array(samples)
        l_std = np.std(samples[:, 0])  # Lightness (Shadows/Highlights)
        a_std = np.std(samples[:, 1])  # Green-Red color spectrum
        b_std = np.std(samples[:, 2])  # Blue-Yellow color spectrum

        # CALIBRATION:
        # 1. Heavily forgive Lightness (shadows are natural).
        # 2. Forgive slight A/B variations (blush/bronzer).
        # 3. Only penalize extreme color banding.
        variance_penalty = (l_std * 0.1) + (a_std * 0.4) + (b_std * 0.4)

        # It is assumed a "perfect" baseline starts at 100, and standard well-applied
        # makeup will have a variance penalty of around 5 to 12.
        score = 100 - variance_penalty
        return round(max(0, min(100, score)), 2)

    def _calculate_base_finish(self, image: np.ndarray, landmarks) -> float:
        """Calculates skin texture using Laplacian variance (edge detection)."""
        h, w, _ = image.shape
        # Grab a 40x40 pixel patch of skin from the left cheek (Index 234)
        cheek_lm = landmarks[234]
        x, y = int(cheek_lm.x * w), int(cheek_lm.y * h)

        box = 20
        y1, y2 = max(0, y - box), min(h, y + box)
        x1, x2 = max(0, x - box), min(w, x + box)

        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            return 85.0  # Fallback if bounding box fails

        # Convert to grayscale and measure sharpness/texture
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        texture_variance = cv2.Laplacian(gray, cv2.CV_64F).var()

        # Optimal skin texture usually sits around 50-150 variance.
        # Too low = beauty filter/blur. Too high = cakey/dry skin.
        score = 100 - abs(100 - texture_variance) * 0.2
        return round(max(0, min(100, score)), 2)

    def _calculate_color_balance(self, image: np.ndarray) -> float:
        """Measures extreme lighting color casts using the Grey World assumption."""
        # Average the B, G, R channels across the entire image
        avg_b = np.mean(image[:, :, 0])
        avg_g = np.mean(image[:, :, 1])
        avg_r = np.mean(image[:, :, 2])

        mean_all = (avg_b + avg_g + avg_r) / 3

        # Calculate how far the channels drift from pure white/neutral light
        deviation = abs(avg_b - mean_all) + abs(avg_g - mean_all) + abs(avg_r - mean_all)

        # High deviation = neon lighting or severe color cast
        score = 100 - (deviation * 1.2)
        return round(max(0, min(100, score)), 2)

    def _calculate_front_metrics(self, image: np.ndarray, landmarks) -> dict:
        """Calculates geometry for front-facing metrics."""

        nose = landmarks[1]
        left_eye = landmarks[33]
        right_eye = landmarks[263]

        dist_left = abs(nose.x - left_eye.x)
        dist_right = abs(right_eye.x - nose.x)
        symmetry_ratio = min(dist_left, dist_right) / max(dist_left, dist_right)

        left_inner = landmarks[133]
        right_inner = landmarks[362]
        eye_alignment = abs(left_inner.y - right_inner.y)

        foundation = self._calculate_foundation_score(image, landmarks)
        # Ensure blend score doesn't accidentally drop below 0 if foundation is low
        blend = max(0.0, foundation - 5.0)

        # 1. Dynamic Lips Score: Checking horizontal symmetry of the mouth corners
        mouth_left = landmarks[61]
        mouth_right = landmarks[291]
        mouth_dist_left = abs(nose.x - mouth_left.x)
        mouth_dist_right = abs(mouth_right.x - nose.x)
        lip_symmetry_ratio = min(mouth_dist_left, mouth_dist_right) / max(
            mouth_dist_left, mouth_dist_right
        )
        dynamic_lips_score = round(lip_symmetry_ratio * 100, 2)

        # 2. Dynamic Front Contour Score: Width of jaw vs width of cheekbones
        jaw_left = landmarks[132]
        jaw_right = landmarks[361]
        cheek_left = landmarks[127]
        cheek_right = landmarks[356]

        jaw_width = abs(jaw_right.x - jaw_left.x)
        cheek_width = abs(cheek_right.x - cheek_left.x)

        # A contoured face typically has a specific ratio between cheek width and jaw width
        contour_ratio = jaw_width / cheek_width
        # Normalize to a 0-100 scale (Assuming 0.90 is a standard sculpted ratio)
        dynamic_contour_score = round(max(0, 100 - (abs(0.90 - contour_ratio) * 200)), 2)

        return {
            "foundation_score": foundation,
            "symmetry_score": round(symmetry_ratio * 100, 2),
            "eyes_score": round(max(0, 100 - (eye_alignment * 500)), 2),
            "lips_score": dynamic_lips_score,
            "contour_score": dynamic_contour_score,
            "blend_score": blend,
            "base_finish_score": self._calculate_base_finish(image, landmarks),
            "color_balance_score": self._calculate_color_balance(image),
            "glam_type": "soft_glam",
            "strengths": ["Even foundation coverage", "Good facial symmetry"],
            "improvements": ["Enhance lip definition"],
            "recommendations": ["Consider a slightly darker lip liner"],
        }

    def _calculate_profile_metrics(self, image: np.ndarray, landmarks, view: str) -> dict:
        """Calculates geometry for left or right profile views."""

        jaw = landmarks[152]
        cheek = landmarks[127] if view == "left" else landmarks[356]

        contour_depth = abs(jaw.x - cheek.x)
        dynamic_contour_score = round(min(100, contour_depth * 400), 2)

        # 2. Dynamic Foundation & Blend Math
        foundation = self._calculate_foundation_score(image, landmarks)
        blend = max(0.0, foundation - 5.0)

        return {
            "foundation_score": foundation,
            "symmetry_score": 75.0,
            "eyes_score": 70.0,
            "lips_score": 75.0,
            "contour_score": dynamic_contour_score,
            "blend_score": blend,
            "base_finish_score": self._calculate_base_finish(image, landmarks),
            "color_balance_score": self._calculate_color_balance(image),
            "glam_type": "soft_glam",
            "strengths": ["Strong contour placement"],
            "improvements": ["Blend contour lines slightly more"],
            "recommendations": ["Use a fluffy brush to diffuse the jawline contour"],
        }
