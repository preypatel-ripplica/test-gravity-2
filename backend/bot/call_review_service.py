"""AI review of a patient's phone calls (FasterQ recordings).

On demand only: an agent presses the button on the Calls page for one patient,
which queues a job; the worker transcribes that patient's calls with speaker
labels and scores them against a clinic call checklist, producing one combined
review plus a review per call.

Why transcribe first instead of handing the audio to one audio model: measured
on real recordings, scoring a speaker-labelled transcript caught that the agent
never gave her name and never proposed an appointment slot, which the audio-only
route scored as fine. Knowing who said what is what makes the review accurate.
"""

from __future__ import annotations


import json
import os
import re
from datetime import timedelta
from typing import Any, Optional

import backend.bot.gcs_service as gcs_service
from backend.bot.database import call_reviews_collection
from backend.bot.llm_service import MODEL_PRICING
from backend.bot.models import CallRecord, CallReview, CallTranscript
from backend.bot.storage import (
    claim_queued_call_review,
    finish_call_review,
    get_call_transcripts,
    list_calls_for_patient,
    reclaim_stale_call_reviews,
    record_ai_usage,
    save_call_transcript,
    touch_call_review,
)
from backend.bot.utils import now_utc

# A call shorter than this is a ring-out or a misdial: there is no conversation
# to review, and transcribing it would only spend money to say so.
CALL_REVIEW_MIN_SECONDS = int(os.getenv("CALL_REVIEW_MIN_SECONDS", "20"))
CALL_REVIEW_MODEL = os.getenv("CALL_REVIEW_MODEL", "gpt-5-mini")
CALL_REVIEW_TRANSCRIBE_MODEL = os.getenv("CALL_REVIEW_TRANSCRIBE_MODEL", "gpt-4o-transcribe-diarize")
# Transcription takes 15-30s per call and the review another ~35s, so the 20s
# default in llm_service would fail every time.
CALL_REVIEW_TIMEOUT = int(os.getenv("CALL_REVIEW_TIMEOUT", "300"))
CALL_REVIEW_STALE_SECONDS = int(os.getenv("CALL_REVIEW_STALE_SECONDS", "600"))
CALL_REVIEW_MAX_CALLS = int(os.getenv("CALL_REVIEW_MAX_CALLS", "12"))
# Billed per minute, not per token, so it cannot live in MODEL_PRICING.
TRANSCRIBE_USD_PER_MINUTE = float(os.getenv("CALL_REVIEW_TRANSCRIBE_USD_PER_MIN", "0.006"))
CALL_REVIEW_SEED = int(os.getenv("CALL_REVIEW_SEED", "7"))

CRITERIA = [
    "opening", "context", "needs", "clinic_info",
    "booking", "objections", "handling", "closing", "compliance",
]

RUBRIC = """You are a call-quality reviewer for an Indian clinic's patient-enquiry follow-up calls.
The patient enquired on WhatsApp and the clinic's bot promised "our representative will contact
you shortly". The agent's job on these calls is to turn that enquiry into a confirmed clinic visit.

Score ONLY the agent, never the patient. Score each criterion 2 (done well), 1 (partial),
0 (missed), or null (genuinely not applicable to this call).
  opening     - greets, gives their own name and the clinic name, confirms the right person
  context     - refers to the patient's WhatsApp enquiry or stated complaint instead of starting cold
  needs       - asks about the complaint: what hurts, how long, prior treatment, existing reports
  clinic_info - gives what the patient needs to decide: doctor, location, timings, consultation fee
  booking     - proposes a concrete date/time and tries to close the appointment
  objections  - handles hesitation (distance, fee, time, "I'll think about it") instead of giving up
  handling    - polite, patient, listens without interrupting, speaks the patient's language, empathetic
  closing     - recaps what was agreed, what to bring, the next step, and closes politely
  compliance  - does NOT diagnose, prescribe, or promise a cure or an outcome over the phone

Write every piece of prose in ENGLISH, whatever language the call was in. Be specific and name
what actually happened in the call; a clinic manager must be able to act on it."""

COMBINED_SUFFIX = """
You are reviewing ALL of this clinic's calls with ONE patient, in time order.
Score every call on all nine criteria. Use null only when a criterion genuinely could not
apply to that call. Do NOT return any percentage - the percentages are computed from your
scores, so only the scores matter.
Return STRICT JSON only:
{"combined_review": "<4-6 sentences for the clinic manager: the story across the calls, what
   keeps going wrong, what is still missing, and what to do on the next call>",
 "agent_missed": ["<something the agent never did on ANY call>", ...],
 "per_call": [{"n": 1,
               "scores": {"opening": 2, "context": 1, "needs": 0, "clinic_info": 1,
                          "booking": 0, "objections": null, "handling": 2, "closing": 0,
                          "compliance": 2},
               "review": "<1-2 sentences about that call>"}, ...]}"""


def _client():
    """The OpenAI client, built per job (the key is read at call time)."""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key, timeout=CALL_REVIEW_TIMEOUT)


def _audio_name(data: bytes, content_type: str) -> tuple[str, str]:
    """What this audio REALLY is. FasterQ hands us 8kHz mono WAV but the pipeline
    stores it as .mp3 with audio/mpeg, and the transcription API rejects the
    mismatch outright ("Audio file might be corrupted or unsupported"). Browsers
    sniff the bytes, which is why playback never noticed."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "call.wav", "audio/wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "call.mp3", "audio/mpeg"
    if data[:4] == b"OggS":
        return "call.ogg", "audio/ogg"
    if data[4:8] == b"ftyp":
        return "call.m4a", "audio/mp4"
    ext = gcs_service.extension_for_mime(content_type, ".mp3")
    return f"call{ext}", (content_type or "audio/mpeg")


def _reviewable(call: CallRecord) -> Optional[str]:
    """None when the call can be reviewed, else why it cannot."""
    if not call.answered:
        return "not answered"
    if call.recording_status != "stored" or not call.recording_gcs_uri:
        return "no recording"
    if (call.duration_seconds or 0) < CALL_REVIEW_MIN_SECONDS:
        return f"under {CALL_REVIEW_MIN_SECONDS}s"
    return None


def _speaker_label(speaker: str, agent_speaker: str) -> str:
    return "AGENT" if speaker == agent_speaker else "PATIENT"


def transcribe_call(call: CallRecord) -> Optional[CallTranscript]:
    """Speaker-labelled transcript for one call, stored so a re-press never pays
    for the same audio twice. Returns None if it could not be transcribed."""
    data, content_type = gcs_service.download_bytes(call.recording_gcs_uri)
    name, mime = _audio_name(data, content_type)
    result = _client().audio.transcriptions.create(
        model=CALL_REVIEW_TRANSCRIBE_MODEL,
        file=(name, data, mime),
        response_format="diarized_json",
        chunking_strategy="auto",
    )
    segments = getattr(result, "segments", None) or []
    # The outbound caller speaks first, so the first speaker is the agent; on an
    # inbound call the patient does. Diarization labels are per-call and arbitrary.
    first = next((getattr(s, "speaker", "") for s in segments if getattr(s, "text", "").strip()), "A")
    agent_speaker = first if call.direction == "outbound" else None
    lines = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        speaker = getattr(segment, "speaker", "") or ""
        if agent_speaker is None:
            lines.append(f"[{'PATIENT' if speaker == first else 'AGENT'}] {text}")
        else:
            lines.append(f"[{_speaker_label(speaker, agent_speaker)}] {text}")
    text = "\n".join(lines) or (getattr(result, "text", "") or "").strip()
    if not text:
        return None

    transcript = CallTranscript(
        call_id=call.id,
        client_id=call.client_id,
        contact_phone=call.contact_phone,
        text=text,
        model=CALL_REVIEW_TRANSCRIBE_MODEL,
        duration_seconds=call.duration_seconds or 0,
    )
    save_call_transcript(transcript)
    _record_transcription_cost(call)
    return transcript


def _record_transcription_cost(call: CallRecord) -> None:
    """Transcription bills per minute, so it gets its own entry rather than
    MODEL_PRICING. Kept in the same monthly counter the AI node uses, so the
    most expensive AI call in the product is visible in GET /usage."""
    if not call.client_id:
        return
    minutes = (call.duration_seconds or 0) / 60.0
    try:
        record_ai_usage(call.client_id, "", "", 0, 0, 0,
                        round(minutes * TRANSCRIBE_USD_PER_MINUTE, 6), 0)
    except Exception as error:  # noqa: BLE001 - accounting must never fail a review
        print(f"CALL REVIEW USAGE ERROR: {error}")


def _record_chat_cost(client_id: str, usage: Any) -> None:
    if not client_id or not usage:
        return
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    rate_in, rate_out = MODEL_PRICING.get(CALL_REVIEW_MODEL.lower(), (0.25, 2.00))
    cost = round(prompt / 1e6 * rate_in + completion / 1e6 * rate_out, 6)
    try:
        record_ai_usage(client_id, "", "", prompt, completion, prompt + completion, cost, 0)
    except Exception as error:  # noqa: BLE001
        print(f"CALL REVIEW USAGE ERROR: {error}")


def _json_chat(client_id: str, system: str, user: str) -> dict:
    response = _client().chat.completions.create(
        model=CALL_REVIEW_MODEL,
        response_format={"type": "json_object"},
        # gpt-5-mini rejects temperature; seed is the only stability lever it takes.
        seed=CALL_REVIEW_SEED,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    _record_chat_cost(client_id, getattr(response, "usage", None))
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0)) if match else {}


def _lead_context(client_id: str, contact_phone: str) -> str:
    """What the bot already collected from this patient, so the reviewer knows
    what the agent was supposed to be following up on."""
    try:
        from backend.bot.storage import find_conversation_by_client_phone
        conversation = find_conversation_by_client_phone(client_id, contact_phone)
        if not conversation:
            return ""
        bits = []
        if conversation.contact_name:
            bits.append(f"patient name: {conversation.contact_name}")
        if conversation.disposition:
            bits.append(f"current disposition: {conversation.disposition}")
        return "; ".join(bits)
    except Exception:  # noqa: BLE001 - context is a nicety, never a failure
        return ""


def review_patient(client_id: str, contact_phone: str) -> dict:
    """Transcribe whatever is missing, then score the whole set in one call.
    Returns the fields to write onto the review document."""
    calls = list_calls_for_patient(client_id, contact_phone, limit=CALL_REVIEW_MAX_CALLS)
    skipped, usable = [], []
    for call in calls:
        reason = _reviewable(call)
        if reason:
            skipped.append({"call_id": call.id, "reason": reason})
        else:
            usable.append(call)

    if not usable:
        return {
            "status": "done", "percent": None, "combined_review": "",
            "agent_missed": [], "per_call": [], "skipped": skipped,
            "calls_covered": [], "error": None,
        }

    have = get_call_transcripts([c.id for c in usable])
    transcripts = []
    for call in usable:
        transcript = have.get(call.id)
        if transcript is None:
            try:
                transcript = transcribe_call(call)
            except Exception as error:  # noqa: BLE001 - one bad recording must
                # degrade the review, not fail it (the contract fetch_call_recording keeps)
                print(f"CALL REVIEW TRANSCRIBE ERROR {call.id}: {error}")
                skipped.append({"call_id": call.id, "reason": "could not transcribe"})
                transcript = None
            touch_call_review(client_id, contact_phone)
        if transcript and transcript.text:
            transcripts.append((call, transcript))
        elif transcript is None and not any(s["call_id"] == call.id for s in skipped):
            skipped.append({"call_id": call.id, "reason": "no speech detected"})

    if not transcripts:
        return {
            "status": "done", "percent": None, "combined_review": "",
            "agent_missed": [], "per_call": [], "skipped": skipped,
            "calls_covered": [], "error": None,
        }

    context = _lead_context(client_id, contact_phone)
    blocks = []
    for index, (call, transcript) in enumerate(transcripts, start=1):
        when = call.started_at.strftime("%d %b %Y %H:%M") if call.started_at else "unknown time"
        blocks.append(
            f"CALL {index} ({call.direction}, {call.duration_seconds}s, {when},"
            f" agent {call.agent_name or 'unknown'}):\n{transcript.text}"
        )
    header = "Lead from WhatsApp." + (f" {context}." if context else "")
    payload = _json_chat(client_id, RUBRIC + COMBINED_SUFFIX, header + "\n\n" + "\n\n".join(blocks))

    per_call = []
    by_n = {int(entry.get("n", 0)): entry for entry in (payload.get("per_call") or [])
            if str(entry.get("n", "")).isdigit()}
    total_earned = total_possible = 0
    for index, (call, _t) in enumerate(transcripts, start=1):
        entry = by_n.get(index) or {}
        earned, possible = _tally(entry.get("scores"))
        total_earned += earned
        total_possible += possible
        per_call.append({
            "call_id": call.id,
            "percent": _pct(earned, possible) or 0,
            "scores": entry.get("scores") if isinstance(entry.get("scores"), dict) else {},
            "review": str(entry.get("review") or "").strip(),
        })

    return {
        "status": "done",
        "percent": _pct(total_earned, total_possible),
        "combined_review": str(payload.get("combined_review") or "").strip(),
        "agent_missed": [str(x) for x in (payload.get("agent_missed") or [])][:12],
        "per_call": per_call,
        "skipped": skipped,
        "calls_covered": [c.id for c, _t in transcripts],
        "error": None,
    }


def _tally(scores: Any) -> tuple[int, int]:
    """(earned, applicable*2) for one call's criterion scores. A criterion the
    model marked null, omitted, or scored out of range simply does not count."""
    if not isinstance(scores, dict):
        return 0, 0
    earned = possible = 0
    for name in CRITERIA:
        value = scores.get(name)
        if value is None:
            continue
        try:
            point = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= point <= 2:
            earned += point
            possible += 2
    return earned, possible


def _pct(earned: int, possible: int) -> Optional[int]:
    """The percentage is arithmetic, not a judgement: earned over applicable.
    Asking the model for a headline number instead swung the same transcripts
    from 56% to 38% between runs, which is useless as a quality metric."""
    if possible <= 0:
        return None
    return max(0, min(100, round(earned * 100 / possible)))


def run_call_review(review: CallReview) -> None:
    """Execute one claimed review. Never raises - a failure is recorded on the
    document so the button can offer a retry."""
    try:
        fields = review_patient(review.client_id, review.contact_phone)
        finish_call_review(review.client_id, review.contact_phone, fields)
    except Exception as error:  # noqa: BLE001
        print(f"CALL REVIEW ERROR {review.client_id} {review.contact_phone}: {error}")
        finish_call_review(review.client_id, review.contact_phone,
                           {"status": "failed", "error": str(error)[:300]})


def drain_call_reviews(max_jobs: int = 1) -> int:
    """Worker tick: put back anything a dead instance left running, then take
    and run queued reviews. Only the instance that wins each claim does the work."""
    reclaim_stale_call_reviews(now_utc() - timedelta(seconds=CALL_REVIEW_STALE_SECONDS))
    done = 0
    for _ in range(max_jobs):
        review = claim_queued_call_review()
        if not review:
            break
        run_call_review(review)
        done += 1
    return done
