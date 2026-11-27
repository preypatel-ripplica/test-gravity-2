"""PDF export for Keywords and topics."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from backend.tg.services.topics import normalize_topics

WEIGHT_LABELS = {
    "high": "High priority",
    "medium": "Medium priority",
    "low": "Low priority",
}


def pdf_filename(client_name: str | None) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(client_name or "topics").strip()).strip("-")
    slug = (slug or "topics")[:60].lower()
    return f"{slug}-topics.pdf"


def _esc(value: Any) -> str:
    return html.escape(str(value or "").strip())


def _score(topic: dict) -> float | None:
    raw = topic.get("recommendation_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _ranked(topics: list[dict]) -> list[dict]:
    rows = [t for t in topics if str(t.get("text") or "").strip()]
    rows.sort(
        key=lambda topic: (
            -(_score(topic) if _score(topic) is not None else -1.0),
            str(topic.get("text") or "").lower(),
        )
    )
    return rows


def _bucketed(topics: list[dict]) -> dict[str, list[dict]]:
    grouped = {"high": [], "medium": [], "low": []}
    for topic in topics:
        if not str(topic.get("text") or "").strip():
            continue
        key = topic.get("weight") if topic.get("weight") in grouped else "medium"
        grouped[key].append(topic)
    return grouped


def build_topics_html(
    *,
    client: dict,
    topics: list[dict] | None = None,
    ranked: bool = False,
) -> str:
    name = str(client.get("name") or "Client").strip() or "Client"
    niche = str(client.get("niche") or "").strip()
    specialty = str(client.get("specialty") or "").strip()
    rows = normalize_topics(topics if topics is not None else client.get("topics"))
    stamped = datetime.now(timezone.utc).strftime("%d %b %Y")
    subtitle_bits = [bit for bit in (niche, specialty) if bit]
    subtitle = " · ".join(subtitle_bits)

    if ranked:
        body = _ranked_table(_ranked(rows))
    else:
        body = _bucket_sections(_bucketed(rows))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_esc(name)} — Topics</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: #111;
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 22px;
      letter-spacing: -0.02em;
    }}
    .meta {{
      color: #5c5a56;
      margin: 0 0 18px;
      font-size: 12px;
    }}
    .rule {{
      height: 3px;
      background: #ff4d00;
      border: 0;
      margin: 0 0 22px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 9px 8px;
      border-bottom: 1px solid #eee;
      vertical-align: top;
    }}
    th {{
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #5c5a56;
    }}
    .num {{
      width: 36px;
      color: #5c5a56;
      font-variant-numeric: tabular-nums;
    }}
    .score {{
      width: 72px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-weight: 700;
    }}
    h2 {{
      margin: 22px 0 8px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .empty {{ color: #5c5a56; }}
  </style>
</head>
<body>
  <h1>{_esc(name)}</h1>
  <p class="meta">Topics{f" · {_esc(subtitle)}" if subtitle else ""} · {stamped} · {len([t for t in rows if str(t.get("text") or "").strip()])} topics</p>
  <hr class="rule" />
  {body}
</body>
</html>
"""


def _ranked_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No topics yet.</p>'
    show_score = any(_score(row) is not None for row in rows)
    head = "<th>#</th><th>Topic</th>"
    if show_score:
        head += "<th class='score'>Score</th>"
    items = []
    for index, topic in enumerate(rows, start=1):
        score = _score(topic)
        score_cell = (
            f"<td class='score'>{int(round(score))}/100</td>" if show_score and score is not None else (
                "<td class='score'></td>" if show_score else ""
            )
        )
        items.append(
            f"<tr><td class='num'>{index:02d}</td><td>{_esc(topic.get('text'))}</td>{score_cell}</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(items)}</tbody></table>"


def _bucket_sections(grouped: dict[str, list[dict]]) -> str:
    chunks: list[str] = []
    for key in ("high", "medium", "low"):
        items = grouped.get(key) or []
        chunks.append(f"<h2>{WEIGHT_LABELS[key]} ({len(items)})</h2>")
        if not items:
            chunks.append('<p class="empty">None</p>')
            continue
        rows = "".join(
            f"<tr><td class='num'>{index:02d}</td><td>{_esc(topic.get('text'))}</td></tr>"
            for index, topic in enumerate(items, start=1)
        )
        chunks.append(
            f"<table><thead><tr><th>#</th><th>Topic</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    return "".join(chunks)


def html_to_pdf_bytes(html_doc: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("PDF export is not available on this server.") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load")
            return page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "16mm",
                    "bottom": "16mm",
                    "left": "14mm",
                    "right": "14mm",
                },
            )
        finally:
            browser.close()


def export_topics_pdf(*, client: dict, topics: list[dict] | None, ranked: bool) -> tuple[bytes, str]:
    rows = normalize_topics(topics if topics is not None else client.get("topics"))
    if not any(str(row.get("text") or "").strip() for row in rows):
        raise ValueError("Add topics before exporting.")
    html_doc = build_topics_html(client=client, topics=rows, ranked=ranked)
    return html_to_pdf_bytes(html_doc), pdf_filename(client.get("name"))
