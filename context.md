# Beacon

Beacon is the platform where internal users manage client work, and client users see analytics and performance. It draws on test-gravity and the CMS, and the core model is being decided again from scratch. This file records product decisions as we confirm them. It does not record ideas that are still open.

## Projects and users

Projects and users are the two main entities.

A project is the client account the work belongs to. One project has many users.

A user is a person who can log in. Each user is one of two types:

- **Internal.** Manages the work. Can see how the work is done, including operational detail such as how videos are posted.
- **Client.** Sees outcomes: analytics, performance, and similar results. Does not see internal working.

## Domains

A project is divided into domains. Primary domains from test-gravity: **videos** and **socialmedia**. Website and whatsappbot may be added later.

Access is granted per project and per domain, not to a whole project only.

Example: user X is internal and has access to project A's videos and socialmedia, and to project B's socialmedia only.

Profile, topics, content plan items, and tasks are **project-wide** (not owned by a single domain).

A client user will usually have access to one project. That is the normal case, not a rule the system must enforce.

## Who controls access

One user is the admin. The admin decides which user can access which project and which domains inside it.

## What each type is shown

The same project can look different to an internal user and a client user. Sections and data are chosen from configuration, based on the user type. That configuration drives what the frontend shows and what the APIs return.

## Core collections

Full durable set is locked in `design.md` (11 collections). Headline:

1. **users**, **projects** (includes profile + topics list), **access**
2. **project_secrets** — manual passwords + OAuth + app configs (typed)
3. **plan_items**, **tasks** (weekly \| custom) — project-wide work/planning
4. **channels**, **videos**, **productions**, **monthly_reports** — videos domain
5. **social_posts**, **social_schedules** — socialmedia domain

Domain data is owned by the project. Access is storage only; member APIs go through project members.

## Where the code lives

The frontend is one app. The backend is split.

`backend/main` holds shared models (users, projects, access, secrets, plan_items, tasks), login, and the Mongo connection. `backend/videos` and `backend/socialmedia` hold that domain’s models. `website` / `whatsappbot` are reserved for later. All domain docs hang off `project_id`.

## Not decided yet

- The full list of domains.
- Whether admin is one role for the whole platform or one admin on each project.
- Whether an admin is always an internal user.
- The actual sections and fields each user type can see. Only the rule is decided: clients see analytics and performance, and they do not see internal working.
- Who may call which user/project endpoint (admin vs self).
