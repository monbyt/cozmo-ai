import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from google import genai
from app.config import get_settings

c = genai.Client(api_key=get_settings().gemini_api_key)
for m in c.models.list():
    # Only show models that support generateContent
    methods = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
    if "generateContent" in methods or not methods:
        print(f"{m.name}  display={getattr(m, 'display_name', '')}  methods={methods}")
