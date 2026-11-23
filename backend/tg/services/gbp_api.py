"""Google Business Profile HTTP calls. No Maps/Places search."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re

import httpx

from backend.tg.database import get_gbp_location, list_gbp_locations, upsert_gbp_location

ACCOUNT_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"
PLACE_ACTIONS_API = "https://mybusinessplaceactions.googleapis.com/v1"
GMB_V4 = "https://mybusiness.googleapis.com/v4"

LOCATION_READ_MASK = ",".join(
    [
        "name",
        "title",
        "storeCode",
        "storefrontAddress",
        "phoneNumbers",
        "websiteUri",
        "regularHours",
        "specialHours",
        "categories",
        "profile",
        "metadata",
        "latlng",
        "openInfo",
        "serviceItems",
    ]
)

PROFILE_PATCH_FIELDS = {
    "title",
    "phoneNumbers",
    "websiteUri",
    "profile",
    "categories",
    "regularHours",
    "specialHours",
    "serviceItems",
}

DAILY_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "WEBSITE_CLICKS",
    "CALL_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
    "MESSAGING_CLICKS",
    "BUSINESS_BOOKINGS",
]


class GbpApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def build_location_patch(update_mask: list[str], location: dict) -> tuple[str, dict]:
    """Keep only whitelisted fields the caller marked as changed."""
    mask = []
    body = {}
    for field in update_mask or []:
        if field not in PROFILE_PATCH_FIELDS:
            raise GbpApiError(400, f"Field '{field}' cannot be updated from this app.")
        if field not in location:
            continue
        mask.append(field)
        body[field] = location[field]
    if not mask:
        raise GbpApiError(400, "No profile fields to update.")
    return ",".join(mask), body


def format_address(address: dict | None) -> str:
    if not isinstance(address, dict):
        return ""
    parts = list(address.get("addressLines") or [])
    for key in ("locality", "administrativeArea", "postalCode"):
        if address.get(key):
            parts.append(str(address[key]))
    return ", ".join(part for part in parts if part)


def _token(creds) -> str:
    token = getattr(creds, "token", None) or ""
    if not token:
        raise GbpApiError(400, "Google Business Profile access token is missing.")
    return token


def _request(creds, method: str, url: str, **kwargs):
    headers = {"Authorization": f"Bearer {_token(creds)}"}
    extra = kwargs.pop("headers", None) or {}
    headers.update(extra)
    try:
        with httpx.Client(timeout=60) as client:
            response = client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise GbpApiError(502, f"Google Business Profile request failed: {exc}") from exc
    if response.status_code >= 400:
        message = response.text
        try:
            payload = response.json()
            message = (payload.get("error") or {}).get("message") or message
        except Exception:  # noqa: BLE001
            pass
        if response.status_code == 403 and "quota" in message.lower():
            message += " Enable the Business Profile APIs and request GBP API access if quota is 0."
        raise GbpApiError(response.status_code, message)
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _paged(creds, url: str, params: dict, key: str) -> list[dict]:
    items = []
    page_token = None
    while True:
        query = dict(params)
        if page_token:
            query["pageToken"] = page_token
        data = _request(creds, "GET", url, params=query)
        items.extend(data.get(key) or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            return items


def list_accounts(creds) -> list[dict]:
    return _paged(creds, f"{ACCOUNT_API}/accounts", {"pageSize": 20}, "accounts")


def list_account_locations(creds, account_name: str) -> list[dict]:
    parent = account_name if account_name.startswith("accounts/") else f"accounts/{account_name}"
    return _paged(
        creds,
        f"{INFO_API}/{parent}/locations",
        {"readMask": LOCATION_READ_MASK, "pageSize": 100},
        "locations",
    )


def get_location(creds, location_name: str) -> dict:
    name = location_name if location_name.startswith("locations/") else f"locations/{location_name}"
    return _request(creds, "GET", f"{INFO_API}/{name}", params={"readMask": LOCATION_READ_MASK})


def patch_location(creds, location_name: str, body: dict, update_mask: str) -> dict:
    name = location_name if location_name.startswith("locations/") else f"locations/{location_name}"
    return _request(
        creds,
        "PATCH",
        f"{INFO_API}/{name}",
        params={"updateMask": update_mask},
        json=body,
    )


def _category_filter(query: str) -> str:
    """Google's displayName filter is a prefix match. Spaces must be quoted."""
    text = re.sub(r"\s+", " ", (query or "").strip())
    if not text:
        return ""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'displayName="{escaped}"'


def search_categories(creds, query: str, region_code: str = "IN") -> list[dict]:
    params = {
        "regionCode": region_code,
        "languageCode": "en",
        "view": "BASIC",
        "pageSize": 20,
    }
    text = re.sub(r"\s+", " ", (query or "").strip())
    attempts = []
    if text:
        attempts.append(_category_filter(text))
        first = text.split(" ", 1)[0]
        if first != text:
            attempts.append(_category_filter(first))
    else:
        attempts.append("")
    last_error = None
    for filt in attempts:
        query_params = dict(params)
        if filt:
            query_params["filter"] = filt
        try:
            data = _request(creds, "GET", f"{INFO_API}/categories", params=query_params)
        except GbpApiError as exc:
            last_error = exc
            if exc.status_code == 400:
                continue
            raise
        return data.get("categories") or []
    if last_error and last_error.status_code != 400:
        raise last_error
    return []


def list_reviews(creds, account_id: str, location_id: str, page_token: str | None = None, page_size: int = 50):
    params = {"pageSize": page_size, "orderBy": "updateTime desc"}
    if page_token:
        params["pageToken"] = page_token
    data = _request(
        creds,
        "GET",
        f"{GMB_V4}/accounts/{account_id}/locations/{location_id}/reviews",
        params=params,
    )
    if not page_token and not data.get("reviews") and data.get("totalReviewCount"):
        plain = {"pageSize": page_size}
        data = _request(
            creds,
            "GET",
            f"{GMB_V4}/accounts/{account_id}/locations/{location_id}/reviews",
            params=plain,
        )
    return data


def list_all_reviews(creds, account_id: str, location_id: str, page_size: int = 50, max_pages: int = 20) -> dict:
    """Follow every next-page token Google returns."""
    collected = []
    seen = set()
    token = None
    total = None
    pages = 0
    for _ in range(max_pages):
        data = list_reviews(creds, account_id, location_id, page_token=token, page_size=page_size)
        pages += 1
        total = data.get("totalReviewCount") or total
        for review in data.get("reviews") or []:
            key = review.get("name") or review.get("reviewId") or id(review)
            if key in seen:
                continue
            seen.add(key)
            collected.append(review)
        token = data.get("nextPageToken")
        if not token:
            break
    return {
        "reviews": collected,
        "totalReviewCount": total or len(collected),
        "pages": pages,
        "complete": len(collected) >= int(total or len(collected)),
    }


def update_review_reply(creds, review_name: str, comment: str) -> dict:
    name = review_name if review_name.startswith("accounts/") else review_name
    return _request(creds, "PUT", f"{GMB_V4}/{name}/reply", json={"comment": comment})


def delete_review_reply(creds, review_name: str) -> dict:
    return _request(creds, "DELETE", f"{GMB_V4}/{review_name}/reply")


def list_local_posts(creds, account_id: str, location_id: str) -> list[dict]:
    return _paged(
        creds,
        f"{GMB_V4}/accounts/{account_id}/locations/{location_id}/localPosts",
        {"pageSize": 20},
        "localPosts",
    )


def _ymd(value: str | None) -> dict | None:
    if not value:
        return None
    year, month, day = value.split("-")
    return {"year": int(year), "month": int(month), "day": int(day)}


def build_local_post_body(
    *,
    summary: str,
    topic_type: str = "STANDARD",
    source_url: str | None = None,
    cta_type: str | None = None,
    cta_url: str | None = None,
    event_title: str | None = None,
    event_start: str | None = None,
    event_end: str | None = None,
    coupon_code: str | None = None,
) -> dict:
    kind = (topic_type or "STANDARD").upper()
    if kind not in {"STANDARD", "EVENT", "OFFER", "ALERT"}:
        raise GbpApiError(400, "Post type must be STANDARD, EVENT, OFFER, or ALERT.")
    body: dict = {"languageCode": "en", "summary": summary, "topicType": kind}
    if source_url:
        body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": source_url}]
    if cta_type and cta_url:
        body["callToAction"] = {"actionType": cta_type, "url": cta_url}
    if kind in {"EVENT", "OFFER"}:
        start = _ymd(event_start)
        end = _ymd(event_end) or start
        if not start:
            raise GbpApiError(400, "Event and offer posts need a start date.")
        body["event"] = {
            "title": event_title or summary[:58],
            "schedule": {"startDate": start, "endDate": end},
        }
    if kind == "OFFER" and coupon_code:
        body["offer"] = {"couponCode": coupon_code}
    return body


def create_local_post(creds, account_id: str, location_id: str, body: dict) -> dict:
    return _request(
        creds,
        "POST",
        f"{GMB_V4}/accounts/{account_id}/locations/{location_id}/localPosts",
        json=body,
    )


def patch_local_post(creds, post_name: str, body: dict, update_mask: str) -> dict:
    return _request(
        creds,
        "PATCH",
        f"{GMB_V4}/{post_name}",
        params={"updateMask": update_mask},
        json=body,
    )


def delete_local_post(creds, post_name: str) -> dict:
    return _request(creds, "DELETE", f"{GMB_V4}/{post_name}")


def list_media(creds, account_id: str, location_id: str) -> list[dict]:
    return _paged(
        creds,
        f"{GMB_V4}/accounts/{account_id}/locations/{location_id}/media",
        {"pageSize": 50},
        "mediaItems",
    )


def delete_media(creds, media_name: str) -> dict:
    return _request(creds, "DELETE", f"{GMB_V4}/{media_name}")


def upload_location_media(creds, account_id: str, location_id: str, data: bytes, content_type: str, category: str) -> dict:
    parent = f"accounts/{account_id}/locations/{location_id}"
    started = _request(creds, "POST", f"{GMB_V4}/{parent}/media:startUpload")
    resource_name = started.get("resourceName")
    if not resource_name:
        raise GbpApiError(502, "Google did not return a media upload resource.")
    _request(
        creds,
        "POST",
        f"https://mybusiness.googleapis.com/upload/v1/media/{resource_name}",
        params={"upload_type": "media"},
        content=data,
        headers={"Content-Type": content_type or "application/octet-stream"},
    )
    media_format = "VIDEO" if (content_type or "").startswith("video/") else "PHOTO"
    return _request(
        creds,
        "POST",
        f"{GMB_V4}/{parent}/media",
        json={
            "mediaFormat": media_format,
            "locationAssociation": {"category": category or "ADDITIONAL"},
            "dataRef": {"resourceName": resource_name},
        },
    )


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _date_param(prefix: str, value: date) -> list[tuple[str, str]]:
    return [
        (f"{prefix}.year", str(value.year)),
        (f"{prefix}.month", str(value.month)),
        (f"{prefix}.day", str(value.day)),
    ]


def fetch_daily_metrics(creds, location_id: str, start: date, end: date) -> dict:
    params: list[tuple[str, str]] = []
    for metric in DAILY_METRICS:
        params.append(("dailyMetrics", metric))
    params.extend(_date_param("dailyRange.startDate", start))
    params.extend(_date_param("dailyRange.endDate", end))
    data = _request(
        creds,
        "GET",
        f"{PERFORMANCE_API}/locations/{location_id}:fetchMultiDailyMetricsTimeSeries",
        params=params,
    )
    return normalize_metrics(data)


def list_place_action_links(creds, location_id: str) -> list[dict]:
    data = _request(
        creds,
        "GET",
        f"{PLACE_ACTIONS_API}/locations/{location_id}/placeActionLinks",
        params={"pageSize": 20},
    )
    return data.get("placeActionLinks") or []


def appointment_link(links: list[dict]) -> dict | None:
    for item in links:
        if item.get("placeActionType") == "APPOINTMENT":
            return item
    return None


def save_appointment_link(creds, location_id: str, uri: str) -> dict | None:
    """Create, update, or remove the merchant appointment link. Empty uri deletes it."""
    current = appointment_link(list_place_action_links(creds, location_id))
    cleaned = (uri or "").strip()
    if not cleaned:
        if current and current.get("name") and current.get("isEditable", True):
            _request(creds, "DELETE", f"{PLACE_ACTIONS_API}/{current['name']}")
        return None
    if current and current.get("name") and current.get("isEditable", True):
        return _request(
            creds,
            "PATCH",
            f"{PLACE_ACTIONS_API}/{current['name']}",
            params={"updateMask": "uri,isPreferred"},
            json={"uri": cleaned, "placeActionType": "APPOINTMENT", "isPreferred": True},
        )
    return _request(
        creds,
        "POST",
        f"{PLACE_ACTIONS_API}/locations/{location_id}/placeActionLinks",
        json={"uri": cleaned, "placeActionType": "APPOINTMENT", "isPreferred": True},
    )


def fetch_search_keywords(creds, location_id: str, start: date, end: date) -> list[dict]:
    """Every monthly search keyword Google returns. Pages are followed until none remain."""
    rows = []
    page_token = None
    while True:
        params = [
            ("monthlyRange.startMonth.year", str(start.year)),
            ("monthlyRange.startMonth.month", str(start.month)),
            ("monthlyRange.endMonth.year", str(end.year)),
            ("monthlyRange.endMonth.month", str(end.month)),
            ("pageSize", "100"),
        ]
        if page_token:
            params.append(("pageToken", page_token))
        data = _request(
            creds,
            "GET",
            f"{PERFORMANCE_API}/locations/{location_id}/searchkeywords/impressions/monthly",
            params=params,
        )
        for item in data.get("searchKeywordsCounts") or []:
            insights = item.get("insightsValue") or {}
            value = insights.get("value")
            if value is None and insights.get("threshold") is not None:
                value = insights.get("threshold")
            rows.append({"keyword": item.get("searchKeyword") or "", "impressions": _num(value)})
        page_token = data.get("nextPageToken")
        if not page_token:
            return rows


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _dated(value: dict) -> str:
    raw = value.get("date") or {}
    if not raw:
        return ""
    return f"{int(raw.get('year') or 0):04d}-{int(raw.get('month') or 0):02d}-{int(raw.get('day') or 0):02d}"


def normalize_metrics(payload: dict) -> dict:
    series: dict[str, dict[str, float]] = {}
    buckets = payload.get("multiDailyMetricTimeSeries") or []
    for bucket in buckets:
        for metric_row in bucket.get("dailyMetricTimeSeries") or []:
            metric = metric_row.get("dailyMetric") or ""
            points = series.setdefault(metric, {})
            dated = ((metric_row.get("timeSeries") or {}).get("datedValues")) or []
            for point in dated:
                day = _dated(point)
                if not day:
                    continue
                points[day] = points.get(day, 0) + _num(point.get("value"))
    out_series = {
        metric: [{"date": day, "value": points[day]} for day in sorted(points)]
        for metric, points in series.items()
    }
    totals = {metric: sum(point["value"] for point in rows) for metric, rows in out_series.items()}
    return {"series": out_series, "totals": totals}


def merge_metric_payloads(payloads: list[dict]) -> dict:
    merged: dict[str, dict[str, float]] = {}
    for payload in payloads:
        for metric, rows in (payload.get("series") or {}).items():
            bucket = merged.setdefault(metric, {})
            for row in rows:
                bucket[row["date"]] = bucket.get(row["date"], 0) + _num(row.get("value"))
    series = {
        metric: [{"date": day, "value": points[day]} for day in sorted(points)]
        for metric, points in merged.items()
    }
    totals = {metric: sum(point["value"] for point in rows) for metric, rows in series.items()}
    return {"series": series, "totals": totals}


def rollup_labels(totals: dict) -> dict:
    search_desktop = _num(totals.get("BUSINESS_IMPRESSIONS_DESKTOP_SEARCH"))
    search_mobile = _num(totals.get("BUSINESS_IMPRESSIONS_MOBILE_SEARCH"))
    maps_desktop = _num(totals.get("BUSINESS_IMPRESSIONS_DESKTOP_MAPS"))
    maps_mobile = _num(totals.get("BUSINESS_IMPRESSIONS_MOBILE_MAPS"))
    return {
        "search_impressions": search_desktop + search_mobile,
        "search_desktop": search_desktop,
        "search_mobile": search_mobile,
        "maps_impressions": maps_desktop + maps_mobile,
        "maps_desktop": maps_desktop,
        "maps_mobile": maps_mobile,
        "website_clicks": _num(totals.get("WEBSITE_CLICKS")),
        "calls": _num(totals.get("CALL_CLICKS")),
        "direction_requests": _num(totals.get("BUSINESS_DIRECTION_REQUESTS")),
        "chat_clicks": _num(totals.get("MESSAGING_CLICKS")),
        "bookings": _num(totals.get("BUSINESS_BOOKINGS")),
    }


def totals_between(series: dict, start: date, end: date) -> dict:
    totals: dict[str, float] = {}
    for metric, points in (series or {}).items():
        total = 0.0
        for point in points or []:
            raw = str((point or {}).get("date") or "")
            try:
                day = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= day <= end:
                total += _num(point.get("value"))
        totals[metric] = total
    return totals


def percent_change(left: float, right: float, days_left: int, days_right: int) -> dict:
    """Change from the left range to the right range. Unequal lengths use a per-day average."""
    days_left = max(1, int(days_left or 1))
    days_right = max(1, int(days_right or 1))
    same = days_left == days_right
    base = float(left or 0) if same else float(left or 0) / days_left
    nxt = float(right or 0) if same else float(right or 0) / days_right
    if base == 0:
        value = 0 if nxt == 0 else None
    else:
        value = round((nxt - base) / base * 100)
    return {
        "percent": value,
        "basis": "total" if same else "per_day",
        "days_a": days_left,
        "days_b": days_right,
    }


def previous_window(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


def sync_managed_locations(client_id: str, creds) -> list[dict]:
    existing = {row.get("location_id"): row for row in list_gbp_locations(client_id)}
    seen = set()
    saved = []
    last_error: GbpApiError | None = None
    for account in list_accounts(creds):
        account_name = account.get("name") or ""
        account_id = account_name.split("/")[-1]
        try:
            locations = list_account_locations(creds, account_name)
        except GbpApiError as exc:
            last_error = exc
            continue
        for location in locations:
            location_name = location.get("name") or ""
            location_id = location_name.split("/")[-1]
            if not location_id:
                continue
            seen.add(location_id)
            prev = existing.get(location_id) or {}
            row = upsert_gbp_location(
                client_id,
                location_id,
                {
                    "account_name": account_name,
                    "account_id": account_id,
                    "account_title": account.get("accountName") or account.get("name") or "",
                    "location_name": location_name,
                    "title": location.get("title") or prev.get("title") or "",
                    "store_code": location.get("storeCode") or "",
                    "address": format_address(location.get("storefrontAddress")),
                    "selected": bool(prev.get("selected")),
                    "profile": location,
                    "synced_at": datetime.utcnow().isoformat(),
                    "available": True,
                },
            )
            saved.append(row)
    for location_id, prev in existing.items():
        if location_id in seen:
            continue
        upsert_gbp_location(client_id, location_id, {**prev, "available": False})
    if not saved and last_error:
        raise last_error
    return saved or list_gbp_locations(client_id)


def require_selected_location(client_id: str, location_id: str | None) -> dict:
    if location_id:
        row = get_gbp_location(client_id, location_id)
        if not row or not row.get("selected"):
            raise GbpApiError(404, "Selected Google Business location was not found.")
        return row
    selected = [row for row in list_gbp_locations(client_id) if row.get("selected")]
    if not selected:
        raise GbpApiError(400, "Choose at least one Google Business location first.")
    return selected[0]
