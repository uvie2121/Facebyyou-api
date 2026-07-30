import asyncio
import os

from app.services.face_analysis import analyze


async def run_test():
    print("🧪 Testing full analysis pipeline...")

    # Ensure your test images are in the root directory
    test_files = ["front.jpg", "left.jpg", "right.jpg"]
    if not all(os.path.exists(f) for f in test_files):
        print("❌ Error: front.jpg, left.jpg, and right.jpg must exist in the root folder.")
        return

    try:
        # Run the pipeline
        result = await analyze(
            user_id="test_user_123",
            session_id="session_001",
            front_key="front.jpg",
            left_key="left.jpg",
            right_key="right.jpg",
            analysis_types=["makeup"],
        )

        print("\n✅ Pipeline Finished Successfully!")
        print("Category Scores:")
        for category, score in result.category_scores.model_dump().items():
          print(f"  - {category}: {score}")
        print(f"Glam Type: {getattr(result.ai_feedback, 'glam_type', 'N/A')}")
        print(f"Strengths: {result.ai_feedback.strengths}")
        print(f"Improvements: {result.ai_feedback.improvements}")
        print(f"Recommendations: {result.ai_feedback.recommendations}")

    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_test())
