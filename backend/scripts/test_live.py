"""Smoke-test the Gemini Live connection. Just opens the socket and closes it."""
import asyncio, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from google import genai
from google.genai import types
from app.config import get_settings
from app.services.live_tools import LIVE_MODEL_ID, build_live_config


async def main():
    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(api_version="v1beta"))
    config = build_live_config(country="US", currency="USD")
    print(f"opening live connection to {LIVE_MODEL_ID}...")
    try:
        async with client.aio.live.connect(model=LIVE_MODEL_ID, config=config) as sess:
            print("CONNECTED — handshake OK, closing.")
            await sess.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="Say exactly: ready.")]),
                turn_complete=True,
            )
            got_audio = False
            got_text = ""
            async for r in sess.receive():
                if r.server_content:
                    sc = r.server_content
                    if sc.output_transcription and sc.output_transcription.text:
                        got_text += sc.output_transcription.text
                    if sc.model_turn:
                        for p in sc.model_turn.parts or []:
                            if p.inline_data and p.inline_data.data:
                                got_audio = True
                    if getattr(sc, "turn_complete", False):
                        break
            print(f"agent said: {got_text!r}, got audio: {got_audio}")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
