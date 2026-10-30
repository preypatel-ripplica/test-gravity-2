from __future__ import annotations
"""TG compatibility layer: mirrors test-gravity's `app` package on top of Beacon's DB.

Modules:
  config    - `settings` + module-level names TG code expects
  auth      - get_current_user (Beacon JWT) / create_access_token
  database  - TG database helper signatures backed by Beacon collections
  clients   - TG client/channel business logic adapted to Beacon
  schemas   - verbatim copy of test-gravity app/schemas.py

Vocabulary mapping: username -> users.email, client_id -> project_id.
"""
