# Profession class playbook

Hand this file to an agent when adding or changing a profession (Creator, XYZ, …).

This is the contract for the content pipeline (videos, static posts, weekly tracker keywords/scripts/metadata). Profile, WhatsApp, and website are **not** profession-owned. Do not fork the app. Do not copy routes. Do not rewrite doctor functions in place.

Live HTTP pipeline is `backend/tg/` only. `backend/videos/` is a stale mirror except `backend/videos/models.py`. `backend/tg/plug/` is a separate product.

---

## How to think about it

Three knobs on the class. Do not mix them.

| Knob | When to use | What the user sees |
|---|---|---|
| **Method** | Step still exists, but this profession should do it differently | Same button, same URL, different body |
| **Capability flag (boolean)** | This profession does not have that step at all | Hide the existing tab/button with `&&`. Doctor stays `True` so nothing moves |
| **Prompt / catalog pack** | Same step, different voice or templates | Same method, different files from `prompts_dir` |

Doctor is the parent implementation. Every missing/empty `profession` on a client is `doctor`. Unknown keys fall back to doctor.

```text
Client.profession  →  get_profession(client)  →  DoctorProfession | CreatorProfession | XyzProfession
                                              →  capabilities() returned on the client payload
```

---

## Files and registration

| Role | Path |
|---|---|
| Registry + lookup | `backend/tg/professions/__init__.py` |
| Base class | `backend/tg/professions/base.py` (or equivalent) |
| Doctor | `backend/tg/professions/doctor.py` |
| Creator stub | `backend/tg/professions/creator.py` |
| Future XYZ | `backend/tg/professions/xyz.py` |
| Doctor prompts (do not move) | `backend/tg/prompts/` |
| Future XYZ prompts | `backend/tg/professions/xyz/prompts/` (same filenames as doctor) |
| Profession setting UI | `frontend/src/pages/ClientPracticeDetails.jsx` |
| Keywords UI (Trends flag) | `frontend/src/pages/ClientSettings.jsx` |
| Content plan UI (Map flag, not wired yet) | `frontend/src/pages/ClientContentPlan.jsx` |

### Backend registry

```python
PROFESSIONS = {
    "doctor": DoctorProfession,
    "creator": CreatorProfession,  # stub until Creator is built
}

def get_profession(client):
    key = (client.get("profession") or "doctor").strip().lower()
    return (PROFESSIONS.get(key) or DoctorProfession)()
```

Every pipeline route must do `profession = get_profession(client)` then call the method. Do not add a second set of endpoints.

### Frontend dropdown

Same keys as the registry. Creator starts disabled.

```js
const PROFESSIONS = [
  { key: 'doctor', label: 'Doctor', enabled: true },
  { key: 'creator', label: 'Creator', enabled: false },
]
```

If the registry line is missing, `get_profession` silently uses doctor. If the dropdown line is missing, a user cannot pick the profession.

---

## Adding a profession later (Creator, then XYZ)

No new architecture. Four steps.

1. **Class** — `backend/tg/professions/xyz.py`

   ```python
   class XyzProfession(Profession):
       prompts_dir = Path(__file__).parent / "prompts"
       uses_google_trends = False          # example: hide Trends
       # uses_video_mapping = False        # only if XYZ has no map step

       def seed_keywords(self, ...):
           ...  # only override what differs
   ```

   Inherit the rest from `Profession` / `DoctorProfession`. If scripts should still sound like the current app, do not override `generate_scripts`.

2. **Prompt pack** — `backend/tg/professions/xyz/prompts/` using the **same filenames** as `backend/tg/prompts/`. Copy every file that mentions doctor / clinic / patient. Anything not copied still reads doctor text if `prompt()` falls back — that is usually wrong for a new profession, so copy the ones you will call.

3. **Two registrations**
   - Backend: `"xyz": XyzProfession` in `PROFESSIONS`
   - Frontend: `{ key: 'xyz', label: 'XYZ', enabled: true }` in Practice details

4. **Wire a hide-flag in UI only if the control is not wrapped yet.** Flags already live on the class and in `capabilities()`. Trends is wrapped. Map / Recommendations / Festivals / monthly report are **not** wrapped until someone adds the `&&`. See [Capabilities](#capabilities-booleans-hide-a-step).

Creator is the same pattern: fill in `CreatorProfession` (today it raises `NotImplementedError`), add `backend/tg/professions/creator/prompts/`, set `enabled: true`.

---

## Capabilities (booleans): hide a step

Ship a **bag**, not one-off fields. Doctor defaults every flag to `True`.

```python
class Profession:
    uses_google_trends = True
    uses_recommendations_tab = True
    uses_video_mapping = True
    uses_festivals = True
    uses_monthly_report = True

    def capabilities(self) -> dict:
        return {
            "uses_google_trends": self.uses_google_trends,
            "uses_recommendations_tab": self.uses_recommendations_tab,
            "uses_video_mapping": self.uses_video_mapping,
            "uses_festivals": self.uses_festivals,
            "uses_monthly_report": self.uses_monthly_report,
        }
```

Client API returns `capabilities` on the client payload. UI reads `client.capabilities.<flag>`.

| Flag | Doctor | Hide this UI | File | Wired in UI? |
|---|---|---|---|---|
| `uses_google_trends` | `True` | Keywords → **Trends Analysis** tab and **Analyze trends** button | `frontend/src/pages/ClientSettings.jsx` | **Yes** (this change) |
| `uses_recommendations_tab` | `True` | Keywords → **Recommendations** tab | `frontend/src/pages/ClientSettings.jsx` | No — wrap later |
| `uses_video_mapping` | `True` | Content Plan → **Generate map** and empty-state **Map keywords** | `frontend/src/pages/ClientContentPlan.jsx` | No — wrap later |
| `uses_festivals` | `True` | Social → Festivals nav / page | `frontend/src/layouts/SocialMediaLayout.jsx`, `frontend/src/pages/ClientSocialFestivals.jsx` | No — wrap later |
| `uses_monthly_report` | `True` | Videos monthly report | report UI under client videos/reports | No — wrap later |

Handlers stay in the file. Doctor still calls them. A profession with the flag `False` never sees the button.

### How to wire `uses_video_mapping` later (example)

Three small edits. Do not rebuild Content Plan.

1. On the profession class: `uses_video_mapping = False`.
2. Wrap existing buttons:

   ```jsx
   {client.capabilities?.uses_video_mapping !== false && (
     <button onClick={handleMap}>Generate map</button>
   )}
   ```

   Same for the empty-state **Map keywords** button.
3. If mapping is off, the empty state currently says “Run 1. Map keywords…”. Change that copy to offer **Generate titles**, or the page is a dead end.

Same `&&` pattern for the other unwired flags. Do **not** add a boolean per prompt file. If the step exists but should sound different, override the method and swap `prompts_dir`.

### Method vs flag

- Creator still generates keywords, but without Google Trends → override `seed_keywords` + `score_keywords`, set `uses_google_trends = False`. Leave `analyze_trends` as a no-op.
- Creator still maps videos, but with different rules → override `map_videos` only. Leave `uses_video_mapping = True`.
- Creator has no map step at all → `uses_video_mapping = False` and wrap the buttons.

---

## Methods you can reimplement

Same UI, same routes. Override on the subclass. Doctor delegates to the current functions listed under **Doctor calls**.

Prompt loaders (`openai_content_plan._load_prompt`, `youtube_metadata._read_prompt`, `social._read_prompt`) take an optional directory; omitted means `backend/tg/prompts/`.

### Keywords

#### `seed_keywords`

- **UI:** Keywords → Topics. Scrape / refresh auto topics. `POST /client.scrape-profile`, `POST /client.refresh-topics`
- **Doctor calls:** sitemap crawl in `backend/tg/services/topics.py` (`collect_sitemap_urls`, `generate_auto_topics`) then `generate_topics_with_openai` in `backend/tg/services/openai_topics.py`
- **Doctor prompts (inline, not files):** `SYSTEM_SITEMAP`, `SYSTEM_SPECIALTY`, `SYSTEM_REFINE` plus `build_sitemap_prompt` / `build_specialty_prompt` / `build_refine_prompt`
- **Override for Creator:** scrape + AI returns keywords **with scores**. Do not use the clinical topic schema (`doctor_youtube_topics`).
- **Related capability:** none. Topics tab stays.

#### `analyze_trends`

- **UI:** Keywords → Trends Analysis → Analyze trends. `POST /client.analyze-trends`
- **Doctor calls:** `analyze_topics_trends` in `backend/tg/services/trends.py` (DataForSEO Google Trends, geo IN)
- **Prompts:** none
- **Override for Creator:** no-op
- **Related capability:** `uses_google_trends` hides the tab

#### `score_keywords`

- **UI:** Keywords → Recommendations → Save recommendations. `POST /client.save-recommendations`
- **Doctor calls:** `apply_recommendation_scores` / `recommendation_score_for` in `backend/tg/services/topics.py` (priority 50/30/10 + trend points, primary cutoff 50)
- **Prompts:** none
- **Override for Creator:** persist the AI scores from `seed_keywords` instead of mixing in trend points
- **Related capability:** `uses_recommendations_tab` if the tab itself should disappear

### Catalogs (data, not HTTP)

#### `topic_instructions`

- Returns the three OpenAI topic system strings. Subclass replaces them without editing `openai_topics.py`.

#### `content_format_catalog`

- **Doctor calls:** `catalog_for_prompt` in `backend/tg/services/content_formats.py` (Long/Short video types)
- Used when generating the content plan. Override if the profession does not use doctor video types (explainer, myth-bust, …).

#### `script_template_catalog`

- **Doctor calls:** `catalog_for_script_prompt` / `template_for` in `backend/tg/services/script_templates.py`
- Used when generating scripts. Override if hook/CTA templates should not be clinical.

#### `prompt(name)` / `prompts_dir`

- Doctor: `backend/tg/prompts/`
- Other professions: their own folder, same filenames

### Videos / content plan / scripts / metadata

#### `map_videos`

- **UI:** Content Plan → Generate map / Map keywords. `POST /client.content-plan.map`
- **Doctor calls:** `map_videos_batch` in `backend/tg/services/openai_content_plan.py` via `map_content_plan_only` / `ensure_video_topic_coverage` in `backend/tg/services/content_plan.py`
- **Prompt:** `content_plan_map_videos.txt`
- **Related capability:** `uses_video_mapping`

#### `generate_content_plan`

- **UI:** Content Plan → generate / regenerate. `POST /client.content-plan.generate`, `POST /client.content-plan.regenerate`
- **Doctor calls:** `enrich_suggestions` in `openai_content_plan.py` via `generate_content_plan` in `content_plan.py`
- **Prompts:** `content_plan_generate.txt` or `content_plan_regenerate.txt`

#### `generate_scripts`

- **UI:** Scripts / content plan generate-scripts. `POST /client.content-plan.generate-scripts`
- **Doctor calls:** `generate_scripts_batch` in `openai_content_plan.py` via `generate_scripts_for_plan` in `content_plan.py`
- **Prompt:** `content_plan_generate_scripts.txt`
- **Also uses:** `script_template_catalog`, doctor profile fields (`_doctor_profile`: name, designation, location)

#### `refine_script`

- **UI:** refine one script. `POST /client.content-plan.refine-script`
- **Doctor calls:** `refine_single_script`
- **Prompt:** `content_plan_refine_script.txt`

#### `generate_youtube_metadata`

- **UI:** generate YT title/description/tags. `POST /client.content-plan-generate-metadata`
- **Doctor calls:** `generate_youtube_metadata` in `backend/tg/services/youtube_metadata.py`
- **Prompts:** `youtube_metadata_generate.txt` + `languages/{hinglish,arabic,russian}.txt`
- **Language limit today:** `normalize_yt_language` only allows `hinglish`, `arabic`, `russian`. Other YouTube languages can exist on the channel grid for tracker rows; metadata generate still refuses them until a language prompt is added.

#### `refine_youtube_metadata`

- **Route:** `POST /client.content-plan-refine-metadata`
- **Doctor calls:** `refine_youtube_metadata`
- **Prompt:** `youtube_metadata_refine.txt`

#### `generate_thumbnail_prompt`

- **Doctor calls:** `generate_youtube_thumbnail_prompt`
- **Prompt:** `youtube_thumbnail_generate.txt`

#### `refine_thumbnail_prompt`

- **Doctor calls:** `refine_youtube_thumbnail_prompt`
- **Prompt:** `youtube_thumbnail_refine.txt`

#### `reference_thumbnail_prompt`

- **Doctor calls:** `reference_thumbnail_prompt`
- **Prompt:** `youtube_thumbnail_reference_edit.txt`

#### `generate_social_caption`

- Used when a **video** is cross-posted to Instagram/Facebook (`POST /video.upload`)
- **Doctor calls:** `generate_social_caption` in `youtube_metadata.py`
- No dedicated `.txt` filename; lives in that service. Override if captions should not be medical.

### Static posts (Instagram / Facebook)

#### `build_static_brief`

- **UI:** Social generate draft. `POST /social.post-draft.generate` (also festival cron)
- **Doctor calls:** `_build_brief` in `backend/tg/routes/social.py`
- **Prompts:** `instagram_post_brief.txt` or `instagram_festive_brief.txt`

#### `static_image_prompt`

- **Doctor calls:** `_image_prompt` in `social.py`
- **Prompt:** `instagram_image_generation.txt`

#### `pick_static_keywords`

- **Routes:** `POST /social.post-sources.get`, `POST /social.keywords.pick`
- **Doctor calls:** `_recommended_keywords` (score ≥ 50) and `_weighted_sample`
- Override if Creator scoring does not use 50 as the cutoff

### Monthly YouTube report

#### `generate_monthly_report` / `refine_monthly_report` / `polish_monthly_report`

- **Routes:** under `backend/tg/routes/report.py` → `backend/tg/services/openai_monthly_report.py`
- **Doctor prompts:** `SYSTEM_GENERATE`, `SYSTEM_REFINE`, `SYSTEM_POLISH` in `backend/tg/prompts/monthly_report.py` (Python, not `.txt`)
- **Related capability:** `uses_monthly_report`

---

## Doctor prompt pack (entire folder)

Do not move or duplicate `backend/tg/prompts/`. `DoctorProfession.prompts_dir` points here.

| File | Used by method |
|---|---|
| `content_plan_map_videos.txt` | `map_videos` |
| `content_plan_generate.txt` | `generate_content_plan` |
| `content_plan_regenerate.txt` | `generate_content_plan` (regenerate) |
| `content_plan_generate_scripts.txt` | `generate_scripts` |
| `content_plan_refine_script.txt` | `refine_script` |
| `youtube_metadata_generate.txt` | `generate_youtube_metadata` |
| `youtube_metadata_refine.txt` | `refine_youtube_metadata` |
| `youtube_thumbnail_generate.txt` | `generate_thumbnail_prompt` |
| `youtube_thumbnail_refine.txt` | `refine_thumbnail_prompt` |
| `youtube_thumbnail_reference_edit.txt` | `reference_thumbnail_prompt` |
| `languages/hinglish.txt` | injected into metadata (`hinglish` key; UI label Hindi) |
| `languages/arabic.txt` | metadata |
| `languages/russian.txt` | metadata |
| `instagram_post_brief.txt` | `build_static_brief` |
| `instagram_festive_brief.txt` | `build_static_brief` (festivals) |
| `instagram_image_generation.txt` | `static_image_prompt` |
| `instagram_style_analysis.txt` | unused in code; still doctor-owned |
| `monthly_report.py` | monthly report generate / refine / polish |

Also doctor-owned, not files:

- `SYSTEM_SITEMAP`, `SYSTEM_SPECIALTY`, `SYSTEM_REFINE` in `backend/tg/services/openai_topics.py`
- Video types in `backend/tg/services/content_formats.py`
- Script templates in `backend/tg/services/script_templates.py`

A new profession that must not sound like a doctor needs its own copies of the prompts it will actually call, plus overrides of `topic_instructions` / catalogs if those lists are clinical.

---

## Leave alone (not profession methods)

Do not put these on the class. They are shared machinery.

- Client CRUD, secrets, credentials, profile sections / doctor reference
- YouTube / Instagram / Facebook OAuth and connect pages
- `POST /video.upload` upload + Graph publish (caption text is profession; the upload is not)
- Weekly tracker card save, notes, stages, destinations URLs
- Narration TTS (`narrate_script_audio`)
- Sitemap HTTP fetch itself (the AI that turns URLs into keywords is `seed_keywords`)
- WhatsApp (`backend/bot/`)
- Website / SEO (`backend/website/`)
- `backend/tg/plug/` (separate creator product, not this profession switch)
- Tracker stage **ids** (`shared_with_doctor`, …). Do not rename stored ids. Labels can be a later class concern.

---

## Creator (intended later, not in the first profession PR)

Expected shape:

```text
uses_google_trends = False          → hide Trends tab
seed_keywords()                     → scrape + AI scored keywords
analyze_trends()                    → no-op
score_keywords()                    → keep AI scores
generate_scripts() and the rest     → doctor until a creator prompt pack exists
```

Do not enable Creator in the Practice details dropdown until those methods and prompts exist.

---

## YouTube languages (related settings, not the profession class)

Profession does not own languages. Per-client YouTube language chips live on the YouTube connection page.

- Stored as `youtube_languages: [{key, label}]` on the client plus `channels.language`
- Hindi stored key stays `hinglish` (tracker label is already “Hindi”). Do not rename it.
- Multiple channels may share one language. One channel cannot be in two languages.
- Instagram and Facebook stay one connection each; they are not per-language.
- Tracker “Where it went out”: no saved list → today’s 3-language matrix. Saved list → those YouTube rows; IG/FB once.
- Metadata generate still only `hinglish` / `arabic` / `russian` until language prompt files are added.

---

## Checklist for the agent

When asked to add profession `xyz`:

- [ ] Create `backend/tg/professions/xyz.py` subclassing `Profession`
- [ ] Override only the methods that differ (table above)
- [ ] Add `backend/tg/professions/xyz/prompts/` with the filenames you will load
- [ ] Set capability flags `False` only for steps that must disappear
- [ ] Register `"xyz": XyzProfession`
- [ ] Enable `{ key: 'xyz', label: 'XYZ', enabled: true }` in Practice details
- [ ] If hiding Map / Recommendations / Festivals / monthly report, add the `&&` on that existing control
- [ ] Do not add routes, do not copy `ClientSettings.jsx`, do not touch WhatsApp/website
- [ ] Verify a doctor client is unchanged (Trends still visible, map still visible, prompts still `backend/tg/prompts/`)
