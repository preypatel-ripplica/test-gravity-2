# Changes — 3 Nov 2026

Today’s work is three layers: Plug branding, live client/tracker cleanup, and a new **Edit tracker** so editors can see and place daily video work.

---

## 1. Branding and theme

**Purpose:** Make the product look like Plug (Ripplica), not the old indigo/slate Gravity UI. Screens should feel like a white desk, with orange only as accent.

**What shipped**

- Wordmark is **Plug** (orange check). Tagline: *Grow content with consistency and discipline*. Footer: `PLUG · BY RIPPLICA`.
- Page canvas is **white**. Ink `#111111`, accent `#FF4D00`, muted `#5C5A56`. Titles: Arial Narrow. UI: Helvetica Neue.
- A very light orange (`#FFF7F3`) is only inside widgets / selected chips — not the whole page.
- Dark orange rail on **both** left and right (app + login).
- Client list cards are white. Login credentials sit in the center of the screen.

**Nitty-gritty**

- `--widget: #fff7f3` is global, so some tables inherited peach. Client settings table is forced white; client names stay ink, not editor-tinted.
- Default doctor-reference sections cannot be deleted: **Video Editing / Generation**, **Meeting / Communication**, **Assets & Learnings**. They are marked `is_default`. Trash only appears on extra sections added with **+ Add section**. Catalog titles still match even if `is_default` was missing on old data.

---


## 2. Edit tracker (new)

**Purpose:** Internal editors need a week calendar of long/short video work — who edits what, on which day, and how many hours — without changing the client’s default editor when they shuffle one video.

Route: `/edit-tracker`. Internal users only.

Roster (`backend/trackers/editors.json`):

| Editor       | Max hours / day |
|--------------|-----------------|
| Yash         | 6               |
| Roshan       | 4               |
| test-editor  | 6               |

Late work defaults to **test-editor**. Default working days: Mon–Sat (6). Doctor videos default **1h**, non-doctor **2h**, overridable per client long/short.

---

### 3.1 Week board

**Purpose:** See this week (or next) as 7 day columns plus an Unassigned lane.

- Columns: Mon–Sun of the calendar week. **This week** (Nov 2–8) vs **Next week** (Nov 9–15).
- **This week** = late incomplete videos + this tracker week’s open long/short.
- **Next week** = only that week’s work. No late cards. Past spill stays on current week.
- Cards that have no `planned_edit_date` in the viewed week sit in **Unassigned**.
- New deliverables (e.g. Bhavesh ads+social) start Unassigned until someone Assigns or drags them.
- Click a card → main tracker for that client/week/card.
- Day badge: **used / capacity** (e.g. `7h / 16h`). Capacity is that editor’s max, or the sum of editors in use in All view.

**Nitty-gritty**

- Tracker weeks are 4 per month. Calendar weeks are Mon–Sun. They are not the same thing; the board maps “this tracker week” onto the current calendar week.
- Only open video cards (`long_video`, `short`) appear. Complete or `did_not_track` cards are skipped.
- Hours on the card always come from the client’s long/short setting (float, 0.5 steps). Changing hours in settings updates the board even if the card already had a stamped value.

---

### 3.2 Working-day circles

**Purpose:** Assign should fill only the days the team is actually working, but people must still be able to park work on Sunday if they want.

- Seven circles Mon–Sun. Click to deselect. Default: Mon–Sat on.
- **All 7 columns always stay on screen.** Off days are visually lighter, not hidden.
- Drag/drop and date dropdown can still put a card on an off day.
- Assign only auto-fills **selected** days. Need at least one selected day.

---

### 3.3 Assign

**Purpose:** One click to pack this week’s (or next week’s) open videos onto working days up to each editor’s daily cap.

Flow:

1. Confirm: *existing placements for this viewed week will be replaced.*
2. Full-screen dotted circling loader until the API finishes.
3. Overflow that does not fit the cap goes **Unassigned** (date cleared).

**How it packs (nitty-gritty)**

- Group cards by editor.
- Sort inside an editor: **late first**, then ready-to-edit, then script-pending / not started, then larger hours first.
- Fill selected days up to `max_hours_per_day`.
- Ready / late work prefers the **earlier half** of the working days (lowest load that still fits).
- Videos still on `planned` or `script_generated` (and not late) prefer the **later half** of the week, so script work does not eat Monday–Tuesday.
- If nothing fits, date is blank → Unassigned.
- Assign does **not** change the client default editor. It writes `editor_id` + `planned_edit_date` on the card.

---

### 3.4 Drag, editor, date (manual)

**Purpose:** After Assign (or instead of it), move one video without wrecking the rest of the week.

- Pointer drag (8px threshold + ghost follower). Not HTML5 DnD — that was glitchy.
- Drop on a day or Unassigned. Optimistic local patch, then API.
- Editor dropdown on the card. Date dropdown lists Unassigned + all 7 days of the viewed week.
- Changing **card editor** sets `editor_overridden: true`. It does **not** write `video_editor_id` / profile Editor.
- Hydrate will **not** snap an overridden card (including Unassigned editor) back to the client default.
- Changing the **client default** (settings or profile) **does** update cards that were never overridden. Hours always follow the client long/short setting.

**Editor vs default (keep these separate)**

| Layer | Field | Meaning |
|-------|--------|---------|
| Client default | `video_editor_id` + profile Editor | Who usually edits this doctor |
| Per video | `editor_id` + `editor_overridden` | Who is actually on this card this week |
| Hours | `long_video_hours` / `short_video_hours` | Always from client prefs, 0.5–12h |

Late cards still default to **test-editor** unless overridden.

---

### 3.5 Editor tabs, All, Micro

**Purpose:** Yash should see only Yash’s pile; ops should see everyone; dense days should be scannable.

- Independent full-width tab bar: **All / Yash / Roshan / test-editor**, each with a light editor tint.
- Cards use the same light bg: Yash warm peach, Roshan blue, test-editor lilac.
- **All view:** day columns **group by editor**. **Unassigned stays a flat list** (not grouped).
- **Board / Micro** toggle (top). Micro hides editor and date fields so the week is just titles.

**Nitty-gritty**

- Native `<select>` on macOS is dark and unthemeable. Editor and date use a custom light menu (`EditFieldMenu`, portal).
- Date menu uses the **card’s editor colors**, not weekday colors — including Unassigned. Unassigned must not fall back to cream if the editor is purple.

---

### 3.6 Client settings (`/edit-tracker/settings`)

**Purpose:** Change every client’s default editor and long/short hours in one table, without opening each doctor profile.

- Gear + **Client settings** to the left of This week / Next week.
- Columns: Client, Default editor, Long hours, Short hours. Search by name.
- Hours: **− / + stepper**, 0.5h steps, 0.5–12. Wheel on the value also steps. Same control on the doctor profile Video Editing section.
- Save patches the project **and hydrates weekly video cards**, so the board updates immediately (unless that card is overridden).

**Nitty-gritty**

- Table background is white (not widget peach). Client names are ink. Only the editor dropdown keeps editor tint.
- Hours used to truncate (`int(1.5)` → `1`) and hydrate only filled empty editors, so old stamped cards ignored new defaults. Board now uses float hours and re-applies default editor whenever `editor_overridden` is false.

---

## 4. Main files

- Theme: `frontend/src/index.css`, `frontend/src/layouts/AppShell.jsx`, `frontend/src/pages/LoginPage.jsx`
- Board: `frontend/src/pages/EditTracker.jsx`
- Settings: `frontend/src/pages/EditTrackerSettings.jsx`, `frontend/src/components/HoursStepper.jsx`
- Profile: `frontend/src/components/client-profile/DoctorReferenceFields.jsx`, `profileUtils.js`
- Backend: `backend/trackers/edit_tracker.py`, `editors.py`, `editors.json`, `crudl.py`
- Stages / late: `backend/trackers/crudl.py`, `frontend/src/components/tracker/trackerUtils.js`
