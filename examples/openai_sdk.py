"""Use Audiovane through the official OpenAI Python SDK (pip install openai).

Any tool that lets you set a custom OpenAI base URL works the same way. The SDK sends
the standard fields; Audiovane's extra ones (pitch, depth, volume, language) go in
`extra_body`.
"""
import os
from openai import OpenAI

client = OpenAI(base_url=os.environ.get("AVS_API_URL", "http://127.0.0.1:8765/v1"),
                api_key=os.environ.get("AVS_API_KEY") or "not-needed")

# text -> speech (model = the engine: kokoro, vctk or xtts)
with client.audio.speech.with_streaming_response.create(
        model="kokoro", voice="kokoro:af_heart", input="Hello from the OpenAI SDK.",
        response_format="wav", speed=0.95,
        extra_body={"pitch": 1.0, "depth": 2.0}) as r:
    r.stream_to_file("sdk.wav")

# speech -> text with word timestamps
with open("sdk.wav", "rb") as f:
    t = client.audio.transcriptions.create(model="whisper-1", file=f,
                                           response_format="verbose_json",
                                           timestamp_granularities=["word"])
print(t.text)
for w in t.words:
    print(f"{w.start:5.2f}-{w.end:5.2f}  {w.word}")
