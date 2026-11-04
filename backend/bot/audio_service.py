"""Audio conversion via ffmpeg. Everything becomes MP3.

- OUTBOUND (agent recording): browsers record WebM/Opus (Chrome) or MP4/AAC (Safari); we transcode
  to MP3 for sending. WhatsApp's Cloud API reliably delivers MP3 but rejects a (valid) OGG/Opus
  voice note with error 131053, so a native waveform voice note is not achievable - the recording
  is sent as an MP3 audio message.
- INBOUND (patient voice note): arrives as OGG/Opus, which Safari can't play in an <audio> element,
  so we transcode to MP3 for cross-browser inbox playback.

ffmpeg reads/writes real temp files (seekable) so the muxer can finalize the container cleanly.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

_TIMEOUT_SECONDS = 30


class AudioTranscodeError(RuntimeError):
    """Raised when ffmpeg/ffprobe fails or produces no output. Callers decide whether to fall
    back (inbound: store the original) or surface an error (outbound send)."""


def _run_ffmpeg(in_bytes: bytes, out_args: list[str], out_suffix: str) -> bytes:
    """Run `ffmpeg -y -i <in> -vn <out_args> <out>` through seekable temp files and return the
    output bytes. Raises AudioTranscodeError on failure or empty output."""
    if not in_bytes:
        raise AudioTranscodeError("No input audio bytes.")

    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as fin:
            fin.write(in_bytes)
            in_path = fin.name
        out_path = in_path + out_suffix

        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", in_path, "-vn", *out_args, out_path]
        try:
            result = subprocess.run(command, capture_output=True, timeout=_TIMEOUT_SECONDS)
        except FileNotFoundError as error:
            raise AudioTranscodeError("ffmpeg is not installed.") from error
        except subprocess.TimeoutExpired as error:
            raise AudioTranscodeError("ffmpeg timed out.") from error

        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", "replace")[:300]
            raise AudioTranscodeError(f"ffmpeg failed (rc={result.returncode}): {detail}")

        with open(out_path, "rb") as fout:
            data = fout.read()
        if not data:
            raise AudioTranscodeError("ffmpeg produced no output.")
        return data
    finally:
        for path in (in_path, out_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def to_mp3(data: bytes) -> bytes:
    """Transcode any audio to MP3 - used for both outbound sends and inbound playback (Safari
    can't play OGG/Opus; MP3 plays everywhere and WhatsApp accepts it for sending)."""
    return _run_ffmpeg(data, ["-c:a", "libmp3lame", "-b:a", "96k", "-ac", "1", "-f", "mp3"], ".mp3")
