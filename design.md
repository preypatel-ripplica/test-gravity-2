# Design

Engineering record for Beacon. Add a section only after the decision is discussed and confirmed.

## Goals

Same product capability as test-gravity, with a clean model:

- Few collections, clear ownership (`project_id`)
- No kitchen-sink blobs
- Consistent POST CRUDL
- Domains: `videos`, `socialmedia` (plus future domains as needed)
- Profile, topics, content plan, and tasks are **project-wide**, not owned by one domain

## Access

A user has a type: `client` or `internal`.

A grant gives one user access to one domain on one project. Checking access is: grant exists for `(user_id, project_id, domain)`.

Project-wide APIs (profile, topics, plan, tasks, secrets): allowed if the user has **any** access row on that project.

`client` vs `internal` controls which fields/sections are returned (configuration later).

## Code layout

```
frontend/
backend/main/           models: users, projects, access, project_secrets, plan_items, tasks
backend/videos/         models: channels, videos, productions, monthly_reports
backend/socialmedia/    models: social_posts, social_schedules
backend/website/        future
backend/whatsappbot/    future
```

Definitions live next to the domain that owns them. Mongo connection + all indexes live in `backend/main/db.py` so one place opens the DB.

---

## Collections (final)

Durable collections: **11**.

Ephemeral: `oauth_states` (not a product collection; TTL handshake only).

### 1. `users` — identity

| field | type | notes |
|---|---|---|
| `id` | string | `user:<uuid>` |
| `email` | string | unique |
| `name` | string | |
| `password_hash` | string \| null | |
| `type` | `internal` \| `client` | |
| `is_active` | bool | |
| `created_at` / `updated_at` | datetime | |

### 2. `projects` — client account + profile + topics list

One document per client. Profile and keyword list live here (1:1, no extra collections).

| field | type | notes |
|---|---|---|
| `id` | string | `project:<uuid>` |
| `name` | string | |
| `status` | `active` \| `archived` | |
| `website_url` | string \| null | |
| `specialty` | string \| null | |
| `designation` | string \| null | |
| `description` | string \| null | |
| `reference_youtube_channel` | string \| null | |
| `ai_videos_started_from` | string \| null | `YYYY-MM` |
| `profile_sections` | array | doctor reference sections |
| `profile_sections[].id` | string | |
| `profile_sections[].title` | string | |
| `profile_sections[].fields` | array | `{ id, label, value }` |
| `topics` | array | keyword catalog (list owned by project) |
| `topics[].id` | string | |
| `topics[].text` | string | |
| `topics[].weight` | `high` \| `medium` \| `low` | |
| `topics[].source` | `manual` \| `auto` | |
| `topics[].trend_score` | number \| null | optional cache |
| `topics[].recommendation_score` | number \| null | optional cache |
| `topics[].…` | | other trend fields as needed, still on the item |
| `created_at` / `updated_at` | datetime | |

**Not** one Mongo row per keyword.

### 3. `access` — grants (internal; no `/access.*` API)

| field | type |
|---|---|
| `id` | string |
| `user_id` | string |
| `project_id` | string |
| `domain` | `videos` \| `socialmedia` \| (`website` \| `whatsappbot` later) |
| `created_at` | datetime |

Unique `(user_id, project_id, domain)`.

### 4. `project_secrets` — passwords + OAuth + app configs

One restricted collection for anything sensitive. Client viewers never read this.

| field | type | notes |
|---|---|---|
| `id` | string | |
| `project_id` | string | |
| `kind` | `manual` \| `oauth` \| `app_config` | |
| `provider` | string | `portal`, `youtube`, `instagram`, `facebook`, … |
| `label` | string | display name |
| `status` | string | e.g. `active`, `revoked`, `expired` |
| `username` | string \| null | manual |
| `secret_encrypted` | string \| null | manual password / app secret |
| `scopes` | string[] | oauth |
| `refresh_token_encrypted` | string \| null | oauth |
| `access_token_encrypted` | string \| null | oauth |
| `expires_at` | datetime \| null | oauth |
| `external_account_id` | string \| null | channel/page id |
| `external_account_name` | string \| null | |
| `metadata` | object | e.g. selected FB page |
| `created_at` / `updated_at` | datetime | |

Indexes: `project_id`, `(project_id, provider, kind)`.

### 5. `plan_items` — content plan (redesigned)

Replaces TG `content_plans` blob. One **row per planned deliverable**, not one kitchen-sink doc.

| field | type | notes |
|---|---|---|
| `id` | string | |
| `project_id` | string | |
| `topic_id` | string \| null | → `projects.topics[].id` |
| `title` | string | |
| `format` | string | e.g. long / short / static |
| `status` | string | planned / scripted / done / … |
| `script` | string | |
| `sort_order` | int | |
| `production_id` | string \| null | → productions when created |
| `created_at` / `updated_at` | datetime | |

Video↔topic mapping lives on `videos.topic_id` when known — **not** a nested coverage dump.

Keyword analysis snapshots (if needed later) are a separate optional cache field or job result — not mixed into this collection.

### 6a. `weekly_trackers` — week production boards (videos domain)

One document per project week. **Not** the same as custom trackers.

| field | type | notes |
|---|---|---|
| `id` | string | `weekly:{project}:{y}:{m}:{w}` |
| `project_id` | string | |
| `year` / `month` / `week` | int | week 1–4 |
| `cards` | array | long/short/static/blog cards with assets, destinations, notes |
| `languages` | string[] | |
| `updated_at` / `updated_by` | | |

### 6b. `custom_trackers` — client todo list (separate)

One document per project. Simple task checklist — **not** week cards.

| field | type | notes |
|---|---|---|
| `id` | string | `custom:{project}` |
| `project_id` | string | |
| `tasks` | array | `{ id, title, done, due_date, comment }` |
| `updated_at` / `updated_by` | | |

### 7. `channels` — YouTube channel (domain `videos`)

| field | type | notes |
|---|---|---|
| `id` | string | YouTube channel id |
| `project_id` | string | |
| `title` | string | |
| `description` | string | |
| `custom_url` | string \| null | |
| `published_at` | string \| null | |
| `view_count` / `subscriber_count` / `video_count` | int | |
| `language` | string \| null | |
| `secret_id` | string \| null | → `project_secrets` oauth row |
| `created_at` / `updated_at` | datetime | |

No raw OAuth tokens on the channel.

### 8. `videos` — synced YouTube library (domain `videos`)

| field | type | notes |
|---|---|---|
| `id` | string | YouTube video id |
| `project_id` | string | |
| `channel_id` | string | |
| `title` | string | |
| `published_at` | string | |
| `thumbnail_url` | string \| null | |
| `view_count` / `like_count` / `comment_count` | int | |
| `duration_seconds` | int \| null | |
| `is_short` | bool | |
| `privacy_status` | string | |
| `topic_id` | string \| null | optional map to keyword |
| `notes` | string | |
| `metadata_fields` | object | |
| `created_at` / `updated_at` | datetime | |

### 9. `productions` — WIP publish package (domain `videos`)

| field | type | notes |
|---|---|---|
| `id` | string | |
| `project_id` | string | |
| `topic_id` | string \| null | |
| `plan_item_id` | string \| null | |
| `topic_text` | string | |
| `locales` | object | per-language title/description/tags/thumbnail |
| `youtube_video_ids` | string[] | links into `videos` after upload |
| `posted_urls` | array | `{ platform, url, language, posted_at }` |
| `created_at` / `updated_at` | datetime | |

Different from `videos`: production exists before anything is on YouTube.

### 10. `monthly_reports` — client narrative (domain `videos`)

| field | type | notes |
|---|---|---|
| `id` | string | |
| `project_id` | string | |
| `report_month` | string | `YYYY-MM` |
| `status` | string | |
| `narrative` | object \| string | |
| `html` | string \| null | |
| `pdf_path` | string \| null | |
| `refine_history` | array | |
| `created_at` / `updated_at` | datetime | |

### 11. `social_posts` — creatives (domain `socialmedia`)

| field | type | notes |
|---|---|---|
| `id` | string | |
| `project_id` | string | |
| `source_type` | string | script / keyword / festival / … |
| `topic_id` | string \| null | |
| `plan_item_id` | string \| null | |
| `brief` | object | headline, caption, cta, … |
| `image_url` | string \| null | |
| `status` | string | draft / queued / published / … |
| `publish_targets` | string[] | instagram, facebook |
| `queue_order` | number \| null | |
| `external_ids` | object | platform post ids / permalinks |
| `created_at` / `updated_at` | datetime | |

### 12. `social_schedules` — publish policy (domain `socialmedia`)

One doc per project (policy, not posts).

| field | type | notes |
|---|---|---|
| `id` | string | = or keyed by `project_id` |
| `project_id` | string | unique |
| `frequency` | string | |
| `selected_days` | string[] | |
| `posts_per_day` | int | |
| `auto_fallback` | bool | |
| `facebook_auto_publish` | bool | |
| `festive_auto_publish` | bool | |
| `updated_at` | datetime | |

Videos have **no** schedule collection; cadence is `tasks` with `kind=weekly`.

---

## Endpoints (final)

POST-only, JSON body, `Authorization: Bearer` except login / first bootstrap user.

### Auth / user / project / members

Unchanged from main CRUDL:

- `auth.login`, `auth.me`
- `user.create|get|list|update|delete`
- `project.create|get|list|update|delete`
- `project.members.list|set|remove`

`project.get` / `project.update` also read/write profile fields and `profile_sections` on `projects`.

### Topics (on `projects.topics`)

| Endpoint | Body | Replaces (TG) |
|---|---|---|
| `topic.list` | `{ project_id }` | topics on client |
| `topic.set` | `{ project_id, topics: [...] }` | replace whole list (clean write) |
| `topic.refresh` | `{ project_id, … }` | `client.refresh-topics` |
| `topic.analyze-trends` | `{ project_id }` | `client.analyze-trends` |
| `topic.save-recommendations` | `{ project_id }` | `client.save-recommendations` |

### Plan items

| Endpoint | Body | Replaces (TG) |
|---|---|---|
| `plan-item.list` | `{ project_id }` | content-plan.get (items) |
| `plan-item.get` | `{ plan_item_id }` | |
| `plan-item.create` | `{ project_id, title, topic_id?, format? }` | |
| `plan-item.update` | `{ plan_item_id, … }` | refine/update script |
| `plan-item.delete` | `{ plan_item_id }` | |
| `plan-item.generate` | `{ project_id, … }` | content-plan.generate → creates items |
| `plan-item.generate-scripts` | `{ project_id, ids? }` | generate-scripts |

Map coverage: set `videos.topic_id` via `video.update` / a small `video.map-topic` — not a coverage blob.

### Tasks

| Endpoint | Replaces (TG) |
|---|---|
| `task.list` | weekly get (filter kind+period), custom get, poc/month summaries |
| `task.get` | one card/issue |
| `task.create` | add card/issue |
| `task.update` | weekly.save / custom.save |
| `task.delete` | remove |
| `task.attach-script` | weekly.attach-script |
| `task.note.add` | weekly.note.add + sheet comments |
| `task.file.upload` | weekly.file.upload |

### Secrets / connections (`project_secrets`)

| Endpoint | Replaces (TG) |
|---|---|
| `secret.list` | credentials list + connection status (redacted) |
| `secret.get` | one row (internal; secrets masked for client type) |
| `secret.upsert` | credentials.save / app config save |
| `secret.delete` | remove |
| `secret.oauth.start` | google.login / IG/FB connect-url |
| `secret.oauth.disconnect` | channel.disconnect / FB disconnect |
| `secret.oauth.select-page` | facebook.page.select |

### Channels / videos / productions / reports

| Endpoint | Replaces (TG) |
|---|---|
| `channel.list\|get\|update\|sync\|disconnect` | channel.* / sync-channels |
| `video.list\|get\|sync\|update\|analytics\|upload` | video.* |
| `production.list\|get\|upsert\|update\|delete` | content_videos flows |
| `report.list\|get\|generate\|refine` | report.* |

### Social

| Endpoint | Replaces (TG) |
|---|---|
| `social.post.list\|get\|generate\|update\|delete\|publish` | social.post.* |
| `social.post.queue.*` | queue add/remove/reorder/edit |
| `social.schedule.get\|update` | social.schedule.* |
| cron publish / festivals | same jobs, cleaner internals |

---

## Explicitly not copied from TG

| TG | Beacon |
|---|---|
| One row per topic | `projects.topics[]` |
| `content_plans` coverage + suggestions mega-doc | `plan_items` + `videos.topic_id` |
| `weekly_trackers` + `custom_trackers` | one `tasks` + `kind` |
| `tracker_sheet_comments` | `tasks.notes` |
| Separate IG/FB/YT connection collections | `project_secrets` typed rows |
| `project_profiles` collection | fields on `projects` |
| `app_state`, Plug, GMB | out of scope |

---

## Implementation order (suggested)

1. Extend `projects` + domain rename (`videos` / `socialmedia`) in main  
2. `project_secrets` + oauth start/disconnect  
3. `tasks`  
4. `plan_items` + topic list APIs  
5. `channels` / `videos` / `productions` / `monthly_reports`  
6. `social_posts` / `social_schedules`
