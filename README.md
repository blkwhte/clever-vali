# Vali — Clever Secure Sync Certification Tool

Vali is an internal tool that automates the technical validation of partner applications seeking Clever Secure Sync certification. It runs a battery of OAuth security and SSO browser tests against a partner's integration and surfaces the results alongside their certification form responses — all in one place.

Vali has two interfaces:

- **Internal dashboard** (`/`) — for the Clever team to run and review tests across all partners
- **Partner mode** (`/partner`) — a self-service interface partners use to test their own integration before submitting the certification form

---

## What Vali Tests

Vali covers the objective, automatable requirements of the certification process. It is designed to complement, not replace, the Clever certification form.

### OAuth Security Tests

These tests make direct HTTP requests to the partner's Redirect URI to verify it handles malicious or malformed requests safely.

| Test | What it checks |
|---|---|
| Missing state parameter | App rejects OAuth callbacks with no `state` parameter (CSRF protection) |
| Forged state parameter | App rejects a `state` value it never issued — not just any state |
| Graceful code rejection | App handles an invalid authorization code without crashing (no 500 errors) |

All OAuth tests include exponential backoff and jitter on 429 responses, retrying up to three times before reporting a rate limit failure.

### SSO Behavior Tests

These tests use Playwright to drive a real browser through the partner's full Clever login flow. They require the `#DEMO Certification ISD - Events` sandbox district to be connected to the partner's application before running.

| Test | What it checks |
|---|---|
| Role coverage | Logs in as a student, teacher, and admin — verifies each role is recognised after login |
| Missing field handling | Logs in as a sparse-profile user — verifies the app handles missing optional fields gracefully |
| Session invalidation | Logs in as two users sequentially — verifies User A's session is invalidated when User B logs in |

### What Vali Does Not Test

The following requirements are evaluated through partner self-reporting on the certification form and human review:

- Matching strategy for existing users
- Archive and restore behavior
- School year rollover handling
- Historical data preservation
- Sync logging and alerting
- Retry logic for API failures

---

## Project Structure

```
vali_core.py        — Test engine: all test functions, test registry, Playwright login helpers, sandbox user config
dashboard.py        — Flask web server: internal dashboard and partner mode UI and API routes
airtable_client.py  — Airtable read/write layer
requirements.txt    — Python dependencies
Dockerfile          — Container definition for Docker builds
.dockerignore       — Files excluded from the Docker image
.github/workflows/  — GitHub Actions workflow for automated image publishing
.env                — Local credentials (never committed — see setup below)
.gitignore          — Ensures .env and runtime artifacts stay out of the repo
```

---

## Setup

### Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A `.env` file with Airtable credentials (get this from a team member — do not share via Slack or email in plaintext)

### Environment variables

Create a `.env` file in any folder on your machine with the following values. Get the actual values from a team member.

```
AIRTABLE_API_TOKEN=your_token_here
AIRTABLE_SECURE_SYNC_BASE_ID=your_base_id_here
AIRTABLE_SECURE_SYNC_TABLE_NAME=your_table_name_here
```

You can generate your own Airtable Personal Access Token by following [these instructions](https://support.airtable.com/articles/9934989703-creating-personal-access-tokens). At a minimum, your token needs the following scopes:

```
data.records:read
data.records:write
```

### Required Airtable columns

The Secure Sync Airtable base needs the following columns for Vali to write results back. Add them if they don't exist:

| Column name | Field type |
|---|---|
| `Vali Status` | Single line text |
| `Vali Last Run` | Single line text |
| `Vali Report` | Long text — **plain text only, rich text must be disabled** |
| `Redirect URI` | Single line text |
| `Login URL` | Single line text |

---

## Running Vali

### With Docker (recommended)

Docker is the recommended way to run Vali — no Python installation, no dependency management, and identical behaviour across all machines.

**1. Pull the latest image**

```bash
docker pull ghcr.io/blkwhte/clever-vali:latest
```

**2. Run the container**

Navigate to the folder containing your `.env` file, then run:

```bash
docker run --env-file .env -p 5001:5000 ghcr.io/blkwhte/clever-vali:latest
```

**3. Open the dashboard**

- Internal dashboard: `http://localhost:5001`
- Partner mode: `http://localhost:5001/partner`

> **Why port 5001?** macOS quietly occupies port 5000 for AirPlay Receiver, which conflicts with Flask. Port 5001 avoids this without requiring any system setting changes.

**Stopping the container:** Press `Ctrl+C` in the terminal, or stop it from Docker Desktop.

**Getting updates:** When a new version is released, pull again and restart:

```bash
docker pull ghcr.io/blkwhte/clever-vali:latest
docker run --env-file .env -p 5001:5000 ghcr.io/blkwhte/clever-vali:latest
```

---

### Without Docker (local Python)

If you'd prefer to run Vali directly with Python — for example, when actively developing the tool — follow these steps instead.

**Requirements:** Python 3.8 or higher

```bash
git clone https://github.com/blkwhte/clever-vali.git
cd clever-vali
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 dashboard.py
```

- Internal dashboard: `http://localhost:5000`
- Partner mode: `http://localhost:5000/partner`

---

## Internal Dashboard

The internal dashboard is for the Clever team. It connects to the Secure Sync Airtable base and shows all partner certification submissions in the sidebar.

**Before running tests on a partner:**
- Connect the `#DEMO Certification ISD - Events` sandbox district to their Clever application
- Ensure their `Redirect URI` and `Login URL` fields are populated in Airtable

**Running tests:**
1. Select a partner from the sidebar
2. Click **Run tests**
3. Results populate automatically when the run completes — no refresh needed
4. Results are written back to the partner's Airtable row automatically

**Tabs:**
- **Test results** — all test outcomes grouped by category with expandable detail messages
- **Airtable responses** — the partner's full certification form responses

**Syncing:** Click the **⟳** button in the sidebar header to pull fresh data from Airtable without losing your current selection.

---

## Partner Mode

Partner mode is a self-service interface that partners use to test their own integration before submitting the certification form.

- **Docker:** `http://localhost:5001/partner`
- **Local Python:** `http://localhost:5000/partner`

The flow has three steps:

1. **Your details** — Partners enter their Dev Account Client ID, Redirect URI, and optionally their Login Page URL
2. **Running** — A progress bar shows test status while tests run in the background
3. **Results** — An overall PASS/FAIL result with expandable detail cards for each test

Partner results are not written to Airtable — they're returned directly to the partner's browser session only.

**Before directing a partner to partner mode:**
- Connect the `#DEMO Certification ISD - Events` sandbox district to their application
- Let them know automated login tests will be run using sandbox credentials

---

## Result Statuses

| Status | Meaning |
|---|---|
| `PASS` | Requirement is met |
| `NEEDS_WORK` | Something unexpected or ambiguous — review the detail message |
| `FAIL` | Requirement is not met — the detail message explains what to fix |
| `SKIPPED` | Test was not applicable (e.g. app doesn't use state parameter, Playwright not installed) |

The overall status is `PASS` only when every test either passes or is intentionally skipped.

For SSO role coverage, a medium-confidence result (redirect detected but user name not visible on page) produces `NEEDS_WORK` rather than `FAIL` — some app types like educational games don't display user names. These are intended for manual spot-check rather than automatic rejection.

---

## Troubleshooting

### Dashboard won't load in browser
- Confirm Docker Desktop is running
- Confirm the container started successfully — the terminal should show `Running on http://0.0.0.0:5000`
- If you see `address already in use`, something else is on port 5001 — try `-p 5002:5000` instead

### OAuth: Missing state rejected — FAIL
The app accepted an OAuth callback with no `state` parameter. Every callback must be rejected if `state` is absent. If your app does not use the state parameter, ensure your certification form reflects this — the test will be marked `SKIPPED` rather than `FAIL`.

### OAuth: Forged state rejected — FAIL
The app accepted a state value (`VALI_CSRF_PROBE_NOT_A_REAL_SESSION`) it never issued. State must be validated against an active session on every callback — not just checked for presence.

### OAuth: Graceful code rejection — FAIL (500 error)
The app crashed when Clever rejected the invalid authorization code. Add error handling around the token exchange step so a rejected code results in a clean redirect or error page.

### SSO: Role coverage — NEEDS_WORK or FAIL
One or more roles did not produce a high-confidence login result. Common causes:

- **Role filtering** — the app may not be provisioning teachers or admins. Check ingestion logic and token scopes.
- **Pagination** — the app may only be fetching the first page of Clever API results.
- **Name not displayed** — apps that don't show user names (e.g. games) will produce a medium-confidence NEEDS_WORK. This is expected and requires a quick manual spot-check.

### SSO: Session invalidation — FAIL
User A's session remained active after User B logged in. Each new Clever login must produce a clean session. See [Clever's shared device documentation](https://dev.clever.com/docs/il-security#shared-devices-session-re-authentication-and-session-invalidation).

### SSO tests all failing / timing out
- Confirm the `#DEMO Certification ISD - Events` district is connected to the partner's app
- Confirm the `Login URL` points to the page with the "Log in with Clever" button
- Check that the partner's local server is running before tests start

---

## Adding a New Test

Vali uses a test registry pattern — adding a new test requires two steps only:

**1. Write the test function in `vali_core.py`:**

```python
def test_my_new_check(config):
    # ... test logic ...
    return _result("My check name", "PASS", "Details here.", "Category Name")
```

**2. Add it to `TEST_REGISTRY` in `vali_core.py`:**

```python
{
    "fn":               test_my_new_check,
    "category":         "Category Name",
    "requires_browser": False,  # True if the test uses Playwright
    "enabled":          True,
},
```

That's it — the test will run automatically in every future run, appear in both the dashboard and partner mode, and be included in the exported report.

---

## Releases

Vali is distributed as a Docker image via GitHub Container Registry. A new image is published automatically whenever a version tag is pushed to the repo:

```bash
# Tag a new release (run from the clever-vali repo directory)
git tag v1.x.x
git push origin v1.x.x
```

GitHub Actions handles the build and publish automatically. Teammates get the update by running `docker pull` before their next session.

---

## For Team Members: Sandbox Configuration

The sandbox users are configured in `SANDBOX_USERS` at the top of `vali_core.py`. All users belong to the `#DEMO Certification ISD - Events` district. Credentials are stored directly in the file — do not commit this file to a public repository.

To add a new sandbox test user, add an entry to `SANDBOX_USERS` with `clever_id`, `sis_id`, `district_id`, `name`, `role`, `username`, and `password`.

The sparse-profile user used for missing field handling is configured separately in `SPARSE_USER` just below `SANDBOX_USERS`.

---

## Questions

Reach out to the Clever Partnerships / Integrations team at [integrations@clever.com](mailto:integrations@clever.com).