from core.config import ENV_FILE, PROJECT_ROOT, load_project_env
import os
import shutil

load_project_env()
print(f"Project root: {PROJECT_ROOT}")
print(f".env exists: {ENV_FILE.is_file()}")
placeholder_markers = ("your_actual_", "your_real_", "replace_with_", "your_groq_api_key_here", "your_sarvam_api_key_here")
groq_key = os.getenv("GROQ_API_KEY", "").strip()
sarvam_key = os.getenv("SARVAM_API_KEY", "").strip()
print(f"GROQ_API_KEY loaded: {bool(groq_key) and not any(x in groq_key.lower() for x in placeholder_markers)}")
print(f"SARVAM_API_KEY loaded: {bool(sarvam_key) and not any(x in sarvam_key.lower() for x in placeholder_markers)}")
print(f"FFmpeg found: {bool(shutil.which('ffmpeg'))}")
print(f"FFprobe found: {bool(shutil.which('ffprobe'))}")
print("Never paste API key values into screenshots or chat.")

vision_model = os.getenv("GROQ_VISION_MODEL", "").strip()
print(f"GROQ_VISION_MODEL configured: {bool(vision_model)} (only required for optional visual analysis)")
