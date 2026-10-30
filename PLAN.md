# Beacon build plan

Goal: same product capability as test-gravity, cleaner collections/CRUDL, plus UI.  
Target codebase: **Beacon** (`beacon/`). test-gravity stays reference only.

---

## 1. Access and visibility (must be solid first)

### Two layers (always both)

| Layer | Question | Mechanism |
|---|---|---|
| **Access** | May this user open this project / domain? | `access` rows: `(user_id, project_id, domain)` |
| **Visibility** | What may they *see* inside? | `users.type`: `internal` \| `client` + field/section config |

### Rules

1. **Login** → token with `user_id`, `type`.
2. **`project.list`** → only projects with ≥1 access row for this user; include `domains[]` from those rows.
3. **Domain route** (`videos` / `socialmedia`) → require access for that domain on `project_id` → else **403**.
4. **Project-wide route** (profile, topics, plan-items, tasks, secrets list metadata) → require **any** access on that project → else **403**.
5. **`client` type** never receives:
   - operational tracker internals (how posting works, raw stages tooling) beyond agreed client-visible notes
   - `project_secrets` plaintext / tokens
   - internal-only task notes (`visibility: internal`)
   - production WIP machinery if marked internal-only
6. **`client` type** does receive (configurable, start with this set):
   - project name + public profile fields
   - analytics (`video.analytics`, reports they are allowed)
   - task notes with `visibility: client` (doctor feedback style)
   - published outcomes / report narratives
7. **`internal` type** receives full operational data for domains they can access.
8. Enforce on **API responses**, not only UI hide. Frontend uses the same rules for menus.

### Helper (implement once in `main`)

```text
require_project_access(user_id, project_id)           # any domain
require_domain_access(user_id, project_id, domain)    # videos | socialmedia
filter_for_viewer(doc, user.type, resource_kind)      # strip fields
```

Admin who-can-call-what (platform admin) remains a later gate; until then authenticated internals with access can manage members if we allow — **decide in phase 0:** only `internal` may call `project.members.*` and `user.*` mutations.

**Phase 0 decision (proposed):**  
- `user.*` mutations + `project.members.*` + `secret.*` writes: **`internal` only**  
- `client`**: read-only on allowed resources  

---

## 2. Endpoint inventory (by phase)

### Phase 0 — Harden main
- Keep: `auth.*`, `user.*`, `project.*`, `project.members.*`
- Add access helpers + `type` checks
- Rename domain values in API to `videos` | `socialmedia` (already in models)
- Extend `project.get` / `project.update` for profile fields + `profile_sections`

### Phase 1 — Topics + secrets (project-wide)
| Endpoint | Access |
|---|---|
| `topic.list` / `topic.set` | any project access; set = internal |
| `topic.refresh` / `analyze-trends` / `save-recommendations` | internal |
| `secret.list` / `get` / `upsert` / `delete` | internal (list redacted status ok for internal) |
| `secret.oauth.start` / `disconnect` / `select-page` | internal |

### Phase 2 — Tasks (project-wide tracker)
| Endpoint | Access |
|---|---|
| `task.list` / `get` | any access; filter notes by visibility for client |
| `task.create` / `update` / `delete` | internal |
| `task.attach-script` / `note.add` / `file.upload` | internal (client may `note.add` only if we allow client-visible notes — start internal-only) |

### Phase 3 — Plan items
| Endpoint | Access |
|---|---|
| `plan-item.list` / `get` | internal (client: hide or summary later) |
| `plan-item.create` / `update` / `delete` | internal |
| `plan-item.generate` / `generate-scripts` | internal |

### Phase 4 — Videos domain
| Endpoint | Access |
|---|---|
| `channel.*` | domain `videos`; mutations internal |
| `video.list` / `get` / `analytics` | domain `videos`; client can read analytics |
| `video.sync` / `update` / `upload` | internal + domain |
| `production.*` | internal + domain |
| `report.list` / `get` | domain; client can read |
| `report.generate` / `refine` | internal |

### Phase 5 — Socialmedia domain
| Endpoint | Access |
|---|---|
| `social.post.*` | domain `socialmedia`; publish/generate = internal; client may list published only |
| `social.schedule.*` | internal + domain |

### Phase 6 — UI (Beacon frontend)
Mirror TG hub, with Beacon access:

1. Login  
2. Project list (from `project.list`)  
3. Project hub: cards for **Videos** / **Social media** / **Profile** (only domains in access)  
4. Videos: channels, library, plan, productions, tracker, reports  
5. Social: posts, schedule, connect accounts  
6. Profile: sections + (internal) secrets  

Client login: hub shows allowed domains; menus omit internal tools; APIs still enforce.

---

## 3. UI map (TG → Beacon)

| TG screen | Beacon route (proposed) | APIs |
|---|---|---|
| Login | `/login` | `auth.login` |
| All clients | `/projects` | `project.list` |
| Client hub | `/projects/:id` | `project.get` + domains from list |
| Profile | `/projects/:id/profile` | `project.get/update`, `secret.*` (internal) |
| Videos overview / channels | `/projects/:id/videos/...` | `channel.*`, `video.*` |
| Content plan / scripts | `/projects/:id/plan` | `topic.*`, `plan-item.*`, `production.*` |
| Weekly / custom tracker | `/projects/:id/tasks` | `task.*` (`kind`) |
| Reports | `/projects/:id/reports` | `report.*` |
| Social generate / schedule | `/projects/:id/social/...` | `social.post.*`, `social.schedule.*` |
| All trackers (POC) | `/tasks` | `task.list` across projects user can access |

---

## 4. File layout for CRUDL

```
backend/main/
  main_crudl.py          # auth, user, project, members (exists)
  topic_crudl.py         # topic.*
  secret_crudl.py        # secret.*
  plan_crudl.py          # plan-item.*
  task_crudl.py          # task.*
  access_guards.py       # require_* + filter_for_viewer
backend/videos/
  crudl.py               # channel, video, production, report
backend/socialmedia/
  crudl.py               # social.post, social.schedule
frontend/                # Vite React, same spirit as TG
```

Register all routers on `main/app.py`.

---

## 5. Delivery order (implementation)

| Step | Deliverable | Done when |
|---|---|---|
| A | Access guards + internal-only writes + profile on project | Cannot read another project’s data; client token stripped |
| B | `topic.*` + basic frontend login + project list + profile | Can edit topics/profile as internal |
| C | `task.*` + tasks UI | Weekly + custom in one UI with kind filter |
| D | `secret.*` + oauth start stubs | Connects stored in `project_secrets` |
| E | `plan-item.*` + plan UI | Generate/list/update items |
| F | Videos CRUDL + videos UI shell | List sync channels/videos; analytics read for client |
| G | Productions + reports | Post-video + monthly report |
| H | Social CRUDL + social UI | Posts + schedule |
| I | Polish visibility config | Config table/file for section flags |

---

## 6. Out of scope for first UI pass

- Full parity of every TG cron/edge case on day one  
- Plug creator app  
- Website / whatsappbot domains  
- Migrating live TG Mongo data (separate migration later)

---

## 7. Immediate next coding step

**Step A:** `access_guards.py` + wire into existing `main_crudl.py` + extend project profile fields in get/update.  
Then **Step B:** `topic_crudl.py` + minimal frontend login/projects/profile.
