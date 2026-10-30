from __future__ import annotations
import base64
import io
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from openai import OpenAI
from backend.tg.config import settings
from backend.tg.services.topics import make_topic
import httpx
from pathlib import Path
from PIL import Image
from backend.tg.services.gcs_storage import upload_bytes

SOCIAL_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "social_assets"

YT_LANGUAGES = ("hinglish", "arabic", "russian")

THUMBNAIL_TEXT_RULES = {
    "hinglish": "If any on-image text is used, write it in Hinglish (Hindi Devanagari mixed with English medical terms).",
    "arabic": "If any on-image text is used, write it in Arabic (right-to-left). Avoid English except for widely recognized medical acronyms.",
    "russian": "If any on-image text is used, write it in Russian (Cyrillic). English medical terms are OK only if commonly searched that way.",
}


def _read_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def normalize_yt_language(language: Optional[str], *, required: bool = True) -> Optional[str]:
    lang = (language or "").strip().lower() or None
    if not lang:
        if required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select at least one language.",
            )
        return None
    if lang not in YT_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language '{language}'. Use hinglish, arabic, or russian.",
        )
    return lang


def _language_instructions(language: str) -> str:
    return _read_prompt(f"languages/{language}.txt")


def _fill_prompt(name: str, **replacements: str) -> str:
    text = _read_prompt(name)
    for key, value in replacements.items():
        text = text.replace("{" + key + "}", value)
    return text


def _is_retryable_openai_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in (408, 409, 429, 500, 502, 503, 504):
        return True
    text = str(exc).lower()
    return "server_error" in text or "server had an error" in text


def _chat_json(
    messages: list,
    *,
    retries: int = 3,
) -> dict:
    """Call chat.completions expecting a JSON object. Retry OpenAI 5xx/rate limits."""
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    kwargs: dict[str, Any] = {
        "model": settings.YT_METADATA_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    effort = (settings.YT_METADATA_EFFORT or "").strip()
    if effort:
        kwargs["reasoning_effort"] = effort

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = openai_client.chat.completions.create(**kwargs)
            content_str = response.choices[0].message.content or ""
            return json.loads(content_str)
        except json.JSONDecodeError as exc:
            last_exc = exc
            print(f"[yt-metadata] invalid JSON (attempt {attempt + 1}/{retries}): {exc}", flush=True)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_openai_error(exc) or attempt == retries - 1:
                raise
            wait = 1.5 * (attempt + 1)
            print(
                f"[yt-metadata] OpenAI error (attempt {attempt + 1}/{retries}), "
                f"retrying in {wait:.1f}s: {exc}",
                flush=True,
            )
            time.sleep(wait)
    raise last_exc or RuntimeError("OpenAI chat JSON call failed")


def _canonical_script_title(topic: dict | None) -> str:
    if not isinstance(topic, dict):
        return ""
    return (
        str(topic.get("title_hinglish") or "").strip()
        or str(topic.get("working_title") or "").strip()
        or str(topic.get("title_en") or "").strip()
    )


def generate_youtube_metadata(
    client_summary: dict,
    topic: dict,
    script: Optional[str] = None,
    user_prompt: Optional[str] = None,
    language: str = "hinglish",
    script_title: Optional[str] = None,
    examples: Optional[List[dict]] = None,
) -> dict:
    """Generate YouTube text metadata using GPT-4o."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is missing, so metadata generation cannot run.",
        )

    language = normalize_yt_language(language)
    locked_title = (script_title or "").strip()
    if not locked_title and script:
        locked_title = _canonical_script_title(topic)
    system_prompt = _fill_prompt(
        "youtube_metadata_generate.txt",
        language_instructions=_language_instructions(language),
    )
    
    # Construct the message content
    text_content = (
        f"Client Profile:\n"
        f"Name: {client_summary.get('name', 'N/A')}\n"
        f"Specialty: {client_summary.get('specialty', 'N/A')}\n\n"
        f"Topic:\n{topic.get('topic_text', '')}\n\n"
    )
    if script:
        text_content += f"Script:\n{script}\n\n"
    if locked_title:
        text_content += f"Script Title:\n{locked_title}\n\n"
    if user_prompt:
        text_content += f"User Instructions:\n{user_prompt}\n\n"
    example_rows = [row for row in (examples or []) if str(row.get("description") or "").strip()][:3]
    if example_rows:
        text_content += (
            "Example descriptions from this channel's recent videos. "
            "Match their structure, length, tone, and hashtag style. "
            "Do not copy their medical claims.\n\n"
        )
        for index, row in enumerate(example_rows, start=1):
            text_content += (
                f"Example {index} title: {row.get('title') or ''}\n"
                f"Example {index} description:\n{str(row.get('description') or '')[:1500]}\n\n"
            )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_content},
    ]

    try:
        result = _chat_json(messages)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate YouTube metadata: {str(e)}"
        )
    if locked_title and language == "hinglish":
        result["yt_title"] = locked_title
    return result

def generate_youtube_thumbnail_prompt(
    client_summary: dict,
    topic: dict,
    script: Optional[str] = None,
    user_prompt: Optional[str] = None,
    reference_image_urls: List[str] = None,
    language: str = "hinglish",
    headline: str = "",
    description: str = "",
    portrait: bool = False,
) -> str:
    """Generate a detailed DALL-E 3 image prompt using GPT-4o."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is missing.",
        )

    language = normalize_yt_language(language)
    topic_text = _topic_text(topic)
    system_prompt = _fill_prompt(
        "youtube_thumbnail_generate.txt",
        language_text_rule=THUMBNAIL_TEXT_RULES[language],
        headline=(headline or topic_text or "Untitled").strip(),
        sub_banner=_sub_banner(description) or topic_text or "Watch the full explanation.",
        composition_rule=_composition_line(portrait),
        layout_rule=_layout_rule(portrait),
        safe_zone_rule=_safe_zone_rule(portrait),
    )
    
    text_content = (
        f"Client Profile:\n"
        f"Name: {client_summary.get('name', 'N/A')}\n"
        f"Specialty: {client_summary.get('specialty', 'N/A')}\n\n"
        f"Topic:\n{topic.get('topic_text', '')}\n\n"
    )
    if script:
        text_content += f"Script:\n{script}\n\n"
    if user_prompt:
        text_content += f"User Instructions:\n{user_prompt}\n\n"
    
    if reference_image_urls:
        content = [{"type": "text", "text": text_content}]
        content.append({"type": "text", "text": "Here are reference thumbnails to mimic stylistically:"})
        for url in reference_image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })
        user_content: Any = content
    else:
        user_content = text_content

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        return _chat_json(messages).get("thumbnail_prompt", "")
    except Exception as e:
        print(f"Failed to generate YouTube thumbnail prompt: {str(e)}")
        return "A professional YouTube thumbnail."

def generate_social_caption(
    yt_title: str,
    yt_description: str,
    yt_tags: List[str]
) -> str:
    """Generate an engaging Instagram/Facebook caption from YouTube metadata."""
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing.")
        
    system_prompt = (
        "You are an expert social media manager. Your task is to take a YouTube video's title, "
        "description, and tags, and convert them into a highly engaging, emoji-rich caption "
        "for Instagram Reels and Facebook Video.\n\n"
        "RULES:\n"
        "1. MUST be under 2000 characters.\n"
        "2. Make it engaging, punchy, and native to Instagram/Facebook.\n"
        "3. Do NOT just copy the description. Summarize the value proposition.\n"
        "4. Include relevant hashtags at the bottom.\n"
        "5. Output ONLY the caption text. No quotes, no markdown blocks."
    )
    
    text_content = (
        f"YouTube Title:\n{yt_title}\n\n"
        f"YouTube Description:\n{yt_description}\n\n"
        f"Tags: {', '.join(yt_tags)}\n"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_content}
    ]
    
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    try:
        response = openai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,  # Use same model as scripts
            messages=messages,
            reasoning_effort="low",
        )
        from backend.tg.services.youtube_api import fit_social_caption
        return fit_social_caption(response.choices[0].message.content.strip())
    except Exception as e:
        print(f"Failed to generate social caption: {e}")
        from backend.tg.services.youtube_api import fit_social_caption
        return fit_social_caption(f"{yt_title}\n\n{yt_description[:1000]}")

def refine_youtube_metadata(
    current_metadata: dict,
    user_prompt: str,
    language: str = "hinglish",
) -> dict:
    """Refine existing YouTube text metadata based on user feedback."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is missing, so metadata refinement cannot run.",
        )

    language = normalize_yt_language(language)
    system_prompt = _fill_prompt(
        "youtube_metadata_refine.txt",
        language_instructions=_language_instructions(language),
    )
    
    text_metadata_only = {
        "yt_title": current_metadata.get("yt_title"),
        "yt_description": current_metadata.get("yt_description"),
        "yt_tags": current_metadata.get("yt_tags"),
    }
    
    text_content = (
        f"Current Metadata:\n{json.dumps(text_metadata_only, indent=2)}\n\n"
        f"User Instructions:\n{user_prompt}\n"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_content},
    ]

    try:
        return _chat_json(messages)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refine YouTube metadata: {str(e)}"
        )

def refine_youtube_thumbnail_prompt(
    current_thumbnail_prompt: str,
    user_prompt: str,
    language: str = "hinglish",
) -> str:
    """Refine existing DALL-E 3 image prompt based on user feedback."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is missing.",
        )

    language = normalize_yt_language(language)
    system_prompt = _fill_prompt(
        "youtube_thumbnail_refine.txt",
        language_text_rule=THUMBNAIL_TEXT_RULES[language],
    )
    
    text_content = (
        f"Current Thumbnail Prompt:\n{current_thumbnail_prompt}\n\n"
        f"User Instructions:\n{user_prompt}\n"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_content},
    ]

    try:
        return _chat_json(messages).get("thumbnail_prompt", current_thumbnail_prompt)
    except Exception as e:
        print(f"Failed to refine YouTube thumbnail prompt: {str(e)}")
        return current_thumbnail_prompt

def _topic_text(topic: dict | None) -> str:
    topic = topic or {}
    return (
        str(topic.get("topic_text") or "").strip()
        or str(topic.get("title_hinglish") or "").strip()
        or str(topic.get("working_title") or "").strip()
        or str(topic.get("title_en") or "").strip()
        or str(topic.get("topic") or "").strip()
    )


def _sub_banner(description: str | None) -> str:
    text = " ".join(str(description or "").split())
    if not text:
        return ""
    for mark in (".", "!", "?"):
        at = text.find(mark)
        if 0 < at <= 90:
            return text[: at + 1].strip()
    return text[:90].rstrip()


def _composition_line(portrait: bool) -> str:
    if portrait:
        return (
            "Vertical 9:16 YouTube Shorts thumbnail. Stack elements top to bottom. "
            "Do not copy a 16:9 two-panel or side-by-side layout. "
            "Keep all headline and sub-banner letters fully inside the frame — never clipped or cut off. "
            "Put all text in a center safe zone: the middle 70% of the width and the middle 50% of the height."
        )
    return "Widescreen 16:9 YouTube thumbnail."


def _layout_rule(portrait: bool) -> str:
    if portrait:
        return (
            "Use any supplied reference images ONLY as a style template: colour scheme, "
            "banner and panel shapes, and the doctor photograph already in the reference. "
            "Do not keep the 16:9 overall layout. Restack branding, photo, diagram, and text "
            "into a vertical 9:16 composition. Do not ask the image model to draw a new person, "
            "and do not list identity features such as age, hair, glasses, or skin tone."
        )
    return (
        "Use any supplied reference images ONLY as a style template: layout, colour scheme, "
        "banner and panel shapes, and the doctor photograph already in the reference. "
        "Do not ask the image model to draw a new person, and do not list identity features "
        "such as age, hair, glasses, or skin tone."
    )


def _layout_keep_line(portrait: bool) -> str:
    if portrait:
        return (
            "KEEP, pixel-faithful and unchanged: the colour scheme, the banner and panel shapes, "
            "and the photo of the doctor already shown in the reference. Do not draw a new person. "
            "Do not keep a 16:9 overall layout. Restack those elements into a vertical 9:16 composition "
            "so no headline or sub-banner letter is cropped."
        )
    return (
        "KEEP, pixel-faithful and unchanged: the overall layout, the colour scheme, "
        "the banner and panel shapes, and the photo of the doctor already shown in the reference. "
        "Do not draw a new person."
    )


def _safe_zone_rule(portrait: bool) -> str:
    if portrait:
        return (
            "Keep ALL headline and sub-banner text fully visible inside a center safe zone "
            "(middle 70% of width and middle 50% of height). Never clip or cut off letters. "
            "Leave the top 25% and bottom 25% as plain background for platform chrome."
        )
    return (
        "Keep all text and important artwork inside the middle 80% of the image vertically. "
        "Leave the top 10% and bottom 10% as plain background with nothing in them."
    )


def reference_thumbnail_prompt(
    *,
    client_summary: dict,
    topic: dict,
    script: Optional[str] = None,
    user_prompt: Optional[str] = None,
    language: str = "hinglish",
    headline: str = "",
    description: str = "",
    portrait: bool = False,
) -> str:
    """Direct image-edit prompt loaded from youtube_thumbnail_reference_edit.txt."""
    topic_text = _topic_text(topic)
    prompt = _fill_prompt(
        "youtube_thumbnail_reference_edit.txt",
        language=normalize_yt_language(language),
        topic=topic_text or "this video",
        headline=(headline or topic_text or "Untitled").strip(),
        sub_banner=_sub_banner(description) or topic_text or "Watch the full explanation.",
        forbid=(
            "the reference headline, bullets, symptom chips, and any video-specific sentences "
            "that are not the clinic logo, clinic name, doctor name card, hospital name, website, or handle"
        ),
        composition=_composition_line(portrait),
        layout_keep=_layout_keep_line(portrait),
        safe_zone=_safe_zone_rule(portrait),
    )
    extras = [
        f"Client: {client_summary.get('name') or 'Client'}",
        f"Specialty: {client_summary.get('specialty') or ''}",
    ]
    if script:
        extras.append(f"Video context:\n{script[:1200]}")
    if user_prompt:
        extras.append(
            "User instructions that are about the image only. Ignore title, description, and tag requests.\n"
            f"{user_prompt}"
        )
    return prompt + "\n\n" + "\n\n".join(part for part in extras if part)


def _store_thumbnail_bytes(image_bytes: bytes) -> str:
    filename = f"{uuid.uuid4()}.png"
    try:
        return upload_bytes("thumbnails", filename, image_bytes)
    except Exception as exc:
        print(f"GCS upload failed: {exc}. Falling back to local disk.")
        SOCIAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        path = SOCIAL_ASSETS_DIR / filename
        path.write_bytes(image_bytes)
        return f"/social.asset/{filename}"


def _crop_aspect(image_bytes: bytes, *, width_ratio: int, height_ratio: int) -> bytes:
    """Center-crop to width_ratio:height_ratio."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    width, height = img.size
    if not width or not height:
        return image_bytes
    target = width_ratio / height_ratio
    current = width / height
    if abs(current - target) < 0.02:
        cropped = img
    elif current > target:
        new_width = int(height * target)
        left = max(0, (width - new_width) // 2)
        cropped = img.crop((left, 0, left + new_width, height))
    else:
        new_height = int(width / target)
        top = max(0, (height - new_height) // 2)
        cropped = img.crop((0, top, width, top + new_height))
    buf = io.BytesIO()
    cropped.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _crop_widescreen(image_bytes: bytes) -> bytes:
    """Center-crop to 16:9. The landscape edits API returns 1536x1024."""
    return _crop_aspect(image_bytes, width_ratio=16, height_ratio=9)


def _crop_portrait(image_bytes: bytes) -> bytes:
    """Center-crop to 9:16. The portrait edits API returns 1024x1536."""
    return _crop_aspect(image_bytes, width_ratio=9, height_ratio=16)


def _reference_image_candidates(reference: dict) -> list[str]:
    video_id = str(reference.get("id") or "").strip()
    stored = str(reference.get("thumbnail_url") or "").strip()
    urls = []
    if video_id:
        urls.extend([
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        ])
    if stored and stored not in urls:
        urls.append(stored)
    return urls


def _download_reference_files(references: List[dict]) -> list[tuple[str, tuple[str, bytes, str]]]:
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for index, reference in enumerate(references[:3]):
            for url in _reference_image_candidates(reference):
                try:
                    response = client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue
                content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
                if not content_type.startswith("image/") or len(response.content) < 1000:
                    continue
                ext = ".png" if "png" in content_type else ".jpg"
                files.append(("image[]", (f"ref-{index}{ext}", response.content, content_type)))
                break
    return files


def generate_reference_thumbnail(prompt: str, references: List[dict], *, portrait: bool = False) -> Optional[str]:
    """Send reference photos to the image edit, the same call Instagram posts use.

    Returns None when the images cannot be downloaded or the edit fails, so the
    caller can fall back to text-only generation.
    """
    if not settings.OPENAI_API_KEY or not references:
        return None
    files = _download_reference_files(references)
    if not files:
        print("[yt-thumbnail] reference images could not be downloaded", flush=True)
        return None
    data = {
        "model": settings.THUMBNAIL_MODEL,
        "prompt": prompt,
        "size": "1024x1536" if portrait else "1536x1024",
        "quality": "medium",
        "n": "1",
        "output_format": "png",
    }
    try:
        with httpx.Client(timeout=180.0) as http_client:
            response = http_client.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        print(f"[yt-thumbnail] reference edit failed, falling back to text generate: {exc}", flush=True)
        return None
    image_row = (payload.get("data") or [{}])[0]
    image_bytes = None
    if image_row.get("b64_json"):
        image_bytes = base64.b64decode(image_row["b64_json"])
    elif image_row.get("url"):
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                image_response = http_client.get(image_row["url"])
                image_response.raise_for_status()
                image_bytes = image_response.content
        except httpx.HTTPError as exc:
            print(f"[yt-thumbnail] could not download edited image: {exc}", flush=True)
            return None
    if not image_bytes:
        return None
    cropped = _crop_portrait(image_bytes) if portrait else _crop_widescreen(image_bytes)
    return _store_thumbnail_bytes(cropped)


def generate_youtube_thumbnail(prompt: str, *, portrait: bool = False) -> str:
    """Generate a 16:9 YouTube thumbnail from text when no reference image is available."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is missing, so thumbnail generation cannot run.",
        )
        
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    try:
        response = openai_client.images.generate(
            model=settings.THUMBNAIL_MODEL,
            prompt=prompt,
            size="1024x1536" if portrait else "1792x1024",
            n=1,
        )
        
        image_data = response.data[0]
        
        # gpt-image-2 returns b64_json, older models return url
        if getattr(image_data, 'b64_json', None):
            image_bytes = base64.b64decode(image_data.b64_json)
        elif getattr(image_data, 'url', None):
            import urllib.request
            resp = urllib.request.urlopen(image_data.url)
            image_bytes = resp.read()
        else:
            raise ValueError("OpenAI did not return image data.")
        cropped = _crop_portrait(image_bytes) if portrait else _crop_widescreen(image_bytes)
        return _store_thumbnail_bytes(cropped)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate YouTube thumbnail: {str(e)}"
        )

