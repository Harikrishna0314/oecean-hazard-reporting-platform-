# OceanGuard — Ocean Hazard Reporting Platform

OceanGuard is a final-year educational project for community-driven ocean hazard reporting, geospatial awareness and near-real-time vessel position sharing.

## Product scope

The main branch is now a single deployable FastAPI product. The previous repository had a disconnected visual mock-up named Frontend while the backend served a non-existent static/index.html path. That mismatch is removed.

Current capabilities:

- Interactive Tamil Nadu coastal map using Leaflet and OpenStreetMap.
- Device geolocation through browser permission.
- Opt-in vessel tracking with configurable update interval and stale-position cutoff.
- Hazard reports stored in SQLite and shown in the live feed and map.
- Optional evidence photo upload with type and 5 MB size validation.
- Dynamic analytics from the same database.
- Administrator Control Room for report verification and user management.
- Weather and marine conditions from Open-Meteo with no API key.
- Google Maps deep-links for coordinates without embedding the paid Google Maps JavaScript API.
- Render Blueprint for a free web service.
- GitHub Actions CI for main and pull requests.

## Zero-cost architecture

The embedded map uses Leaflet with OpenStreetMap tiles. Google Maps JavaScript is intentionally not used because a production Maps JavaScript integration requires an API key and billing. Every report and vessel marker has an Open in Google Maps link instead.

Weather and marine conditions are loaded from Open-Meteo. Its free API is available for non-commercial use without an API key, with usage limits and attribution requirements. The application labels the information as model data and does not present it as an official emergency warning.

No paid API key is required by this repository.

## Render

The root render.yaml defines:

- free Python web service
- pip install from requirements.txt
- uvicorn backend:app
- /healthz health check
- generated APP_SECRET
- SQLite at /tmp/oceanguard/oceanguard.db

Render Free instances use an ephemeral filesystem, so SQLite here is appropriate for a final-year demonstration but is not durable storage across every restart or redeploy.

The service can be linked to main with automatic redeploys on push.

## Local run

Install Python 3.11 or newer.

Run:

1. pip install -r requirements.txt
2. uvicorn backend:app --reload
3. Open http://127.0.0.1:8000

Health endpoint: http://127.0.0.1:8000/healthz

Demo administrator:

- username: admin
- password: admin123

For any public or long-lived deployment, set ADMIN_PASSWORD to a strong secret.

## API surface

GET /healthz
GET /api/config
POST /api/auth/register
POST /api/auth/login
GET /api/auth/me
GET /api/categories
GET /api/reports
GET /api/reports/{id}
POST /api/reports
PATCH /api/reports/{id} (admin)
POST /api/reports/{id}/upvote
DELETE /api/reports/{id} (admin)
GET /api/analytics/stats
GET /api/notifications
POST /api/notifications/{id}/read
POST /api/notifications/clear
GET /api/users (admin)
PATCH /api/users/{id}/role (admin)
PATCH /api/users/{id}/status (admin)
GET /api/tracking
POST /api/tracking
DELETE /api/tracking/{vessel_id}
GET /api/weather
GET /api/marine

## Operational workflow for the project defense

1. Open Dashboard.
2. Inspect live modelled marine conditions.
3. Open Report Hazard.
4. Press Use my location to capture device GPS.
5. Submit an observed hazard with a severity and optional image.
6. Verify that the report appears in the feed and map.
7. Open Control Room and sign in.
8. Change the report from Pending to Verified.
9. Open Analytics and show that the totals changed.
10. Open Live Map, enter a vessel call sign and enable tracking.
11. Show the moving live position and Google Maps hand-off link.

## Auditing discipline

For meaningful repository changes, the intended engineering loop is:

- inspect the current main tree
- make an atomic change
- fetch the resulting files back from main
- run consistency checks
- run Python compile and pytest
- inspect GitHub Actions status
- fix any mismatch and repeat

## Known limitations

1. Render Free can sleep after inactivity.
2. Render Free storage is ephemeral; the SQLite database is not a permanent production database.
3. OpenStreetMap standard tiles are a community tile service with usage rules and best-effort availability. Keep visible attribution and do not bulk-download tiles.
4. Open-Meteo free access is non-commercial and rate-limited.
5. Browser geolocation and live tracking require explicit end-user permission.
6. Live tracking is designed for demonstration and cooperative reporting, not authenticated maritime telemetry.
7. Modelled weather and marine conditions are informative and must not be treated as official safety or navigation instructions.

## Attribution

Keep OpenStreetMap attribution visible in the map and Open-Meteo attribution in the product documentation/footer when deploying.
