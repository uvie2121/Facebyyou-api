import json

from openai import OpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import AIFeedback, LightingCondition

logger = get_logger(__name__)

SYSTEM_PROMPT = """
You are a top-tier makeup artist and beauty consultant. 
You are analyzing a user's facial makeup scores from an AI vision engine across 3 angles (Front, Left Profile, Right Profile).
Your goal is to provide encouraging, professional, and specific feedback.
- If a score is above 90, praise it as a strength.
- If a score is below 70, provide one very specific, actionable technique to improve it.
- Keep your tone supportive but expert level.
- Feedback should be tailored to glam type.
- KEEP EACH POINT CONCISE: Limit each string in the arrays to 1-2 clear sentences maximum so the JSON remains compact.
You will receive an 'environmental_factors.lighting_condition' variable. If this value is 'harsh_flash', you must actively acknowledge it in your feedback. State that the harsh lighting may have artificially lowered their base finish or color balance scores, and reassure the user that their foundation likely looks much smoother in natural light. Recommend they retest in natural lighting for a more accurate assessment.

HISTORICAL PROGRESS TRACKING:
You may receive a 'previous_feedback' object summarizing what the user was advised to work on (both previous 'improvements' and previous 'recommendations') during their last session.
- Look at the new images and scores. If the user improved on areas previously flagged for improvement or followed prior recommendations, celebrate their progress explicitly as the FIRST item in your 'strengths' array (e.g., "Great job blending your contour line—much smoother than last time!").
- If those areas still need work, gently encourage them without sounding repetitive.

Analyze the provided metrics and return a JSON object ONLY. 
Do not include any conversational text nor any simple phrases. Use this exact structure:
{
    "glam_type": "string",
    "strengths": ["string", "string"],
    "improvements": ["string"],
    "recommendations": ["string"]
}
"""


class NvidiaFeedbackService:
    def __init__(self):
        self.client = (
            OpenAI(base_url=settings.NIM_BASE_URL, api_key=settings.NIM_API_KEY)
            if settings.NIM_API_KEY
            else None
        )
        self.model_name = settings.NIM_MODEL_NAME

    @staticmethod
    def _fallback() -> dict:
        return AIFeedback(
            glam_type="soft_glam",
            strengths=["Balanced makeup application", "Good facial symmetry"],
            improvements=["Focus on blending contour edges"],
            recommendations=["Use a damp beauty sponge for a smoother base finish"],
        ).model_dump()

    def generate_feedback(
        self,
        vision_output: dict,
        lighting_condition: LightingCondition = LightingCondition.BALANCED,
        previous_feedback: dict[str, list[str]] | str | None = None,
    ) -> dict:
        if self.client is None:
            logger.warning("NIM feedback skipped because NIM_API_KEY is not configured")
            return self._fallback()

        urls = vision_output["image_urls"]
        math_data = vision_output["analysis_results"]

        # Safely extract URLs whether urls is a dict or a list
        if isinstance(urls, dict):
            front_url = urls.get("front") or list(urls.values())[0]
            left_url = urls.get("left") or list(urls.values())[1]
            right_url = urls.get("right") or list(urls.values())[2]
        else:
            front_url, left_url, right_url = urls[0], urls[1], urls[2]

        # Format historical context block incorporating improvements & recommendations
        if isinstance(previous_feedback, dict):
            prev_imp = "; ".join(previous_feedback.get("improvements", [])) or "None"
            prev_rec = "; ".join(previous_feedback.get("recommendations", [])) or "None"
            history_context = (
                f"PREVIOUS SESSION HISTORICAL CONTEXT:\n"
                f"- Previous Improvements Identified: {prev_imp}\n"
                f"- Previous Recommendations Given: {prev_rec}\n"
                f"Check if they improved on these areas!"
            )
        elif isinstance(previous_feedback, str) and previous_feedback:
            history_context = (
                f"PREVIOUS SESSION ADVICE GIVEN TO USER: '{previous_feedback}'\nCheck if they improved on this!"
            )
        else:
            history_context = "PREVIOUS SESSION HISTORICAL CONTEXT: None (First analysis or no prior history available)."


        prompt = f"""
        {SYSTEM_PROMPT}

        ENVIRONMENTAL CONTEXT:
        The lighting in this photo was assessed as: '{lighting_condition.value}'.

        UNIFIED METRICS & SCORES:
        {json.dumps(math_data, indent=2)}

        {history_context}

        INSTRUCTIONS:
        1. DO NOT change, recalculate, or alter any numerical scores or coordinates.
        2. Look across all 3 images to understand the application and provide advice based on the metrics.
        3. Incorporate the historical context and previous advice into your analysis.
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": front_url}},
                            {"type": "image_url", "image_url": {"url": left_url}},
                            {"type": "image_url", "image_url": {"url": right_url}},
                        ],
                    }
                ],
                temperature=0.3,
                max_tokens=1500,
                response_format={"type": "json_object"},
                timeout=settings.NIM_TIMEOUT_SECONDS,
            )

            raw_content = response.choices[0].message.content
            if not raw_content:
                raise ValueError("NIM returned an empty response")
            feedback = AIFeedback.model_validate_json(raw_content)
            logger.info("NIM feedback generated")
            return feedback.model_dump()

        except Exception:
            logger.exception("NVIDIA NIM feedback generation failed")
            return self._fallback()
