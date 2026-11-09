#!/usr/bin/env bash
# AI Voice Studio Local API with curl. The app (or `AI_Voice_Studio --headless`) must be running.
#   AVS_API_KEY=your-key ./examples/curl.sh
API="${AVS_API_URL:-http://127.0.0.1:8765/v1}"
AUTH=()
[ -n "$AVS_API_KEY" ] && AUTH=(-H "Authorization: Bearer $AVS_API_KEY")

echo "# what is installed"
curl -s "${AUTH[@]}" "$API/models"; echo

echo "# speech with effects (speed 0.25-4, pitch -12..12, volume 0-2, depth -8..8, + = deeper)"
curl -s "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"model":"kokoro","voice":"kokoro:af_heart","input":"Hello from the command line.","speed":0.9,"pitch":-1,"depth":2,"response_format":"wav"}' \
  "$API/audio/speech" -o hello.wav
command -v file >/dev/null && file hello.wav || ls -l hello.wav

echo "# speech to text"
curl -s "${AUTH[@]}" -F file=@hello.wav -F model=whisper-1 "$API/audio/transcriptions"; echo

echo "# word timestamps"
curl -s "${AUTH[@]}" -F file=@hello.wav -F model=whisper-1 -F response_format=verbose_json \
  -F "timestamp_granularities[]=word" "$API/audio/transcriptions"; echo
