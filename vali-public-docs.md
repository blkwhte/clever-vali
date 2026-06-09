# Vali — Internal Capabilities Overview

**Last updated:** June 2026
**Status:** Active development — paused pending reprioritization
**Maintained by:** Clever Partnerships / Integrations team

---

## What Is Vali?

Vali is an internal tool built to automate the technical validation of partner applications seeking Clever Secure Sync certification. It reduces manual review time by programmatically testing integration requirements that are objective and observable, while surfacing partner self-reported responses for requirements that require human judgment.

Vali is built in Python and runs as a local web dashboard. It connects to the team's existing Airtable certification base to pull partner data and write test results back — meaning your team reviews everything in one place rather than juggling separate tools.

---

## Architecture Overview

Vali is made up of three components that work together:

**`vali_core.py` — Test engine**
Contains all test logic, organized around a central test registry. Each test is a self-contained function that returns a standardized result. Adding a new test requires writing one function and adding one entry to the registry — no changes to any other part of the codebase.

**`airtable_client.py` — Data layer**
Handles all communication with the Clever Secure Sync Airtable base. Pulls partner certification form responses, maps field names to internal keys, and writes Vali test results back to each partner's row after a run.

**`dashboard.py` — Web interface**
A Flask-based local web app your team runs on their machine. Provides a partner sidebar, test results view, Airtable responses view, and controls for running and re-running tests. Results update automatically after each test run without requiring a page refresh.

---

## Current Test Coverage

Vali currently runs six automated tests across two categories.

### OAuth Security Tests

These tests make direct HTTP requests to the partner's OAuth callback URL (Redirect URI) to verify it handles bad or malicious requests safely. They run against a live server and do not require any setup beyond the partner having their app running.

**Missing state parameter**
Sends an OAuth callback request with no `state` parameter. A correctly implemented app must reject this with a 400, 401, or 403 response. This verifies that CSRF protection is in place.

**Forged state parameter**
Sends an OAuth callback with a state value (`VALI_CSRF_PROBE_NOT_A_REAL_SESSION`) that was never issued by the app. A correctly implemented app must validate the state value against its own session store and reject anything it didn't issue — not just check that some state was present.

**Graceful code rejection**
Sends an invalid authorization code to the callback URL. Verifies that the app handles a rejected code cleanly (redirecting or returning a client error) rather than crashing with a 500. A 500 response here typically indicates missing error handling around the token exchange step.

All three OAuth tests include exponential backoff with jitter on 429 responses, retrying up to three times before reporting a rate limit failure.

### SSO Behavior Tests (Playwright)

These tests use Playwright to drive a real Chromium browser through the partner's full Clever SSO login flow. They require the `#DEMO Certification ISD - Events` sandbox district to be connected to the partner's application before running.

The login flow Playwright navigates is:

1. Navigate to the partner's login page
2. Click the "Log in with Clever" button
3. Handle Clever's auth method picker (select Password)
4. Handle Clever's school picker (enter district ID, select sandbox district)
5. Complete username and password login
6. Detect success or failure on the partner's app

**SSO role coverage**
Logs into the partner's app as a student, teacher, and admin user sequentially, using sandbox district credentials. Verifies that each role is recognized after login. This catches the most common data ingestion failures — if Teacher 50 can't log in, the app isn't provisioning teachers regardless of what their database contains.

Success detection uses a layered approach: first looks for the user's name on the page (high confidence), then checks for error keywords (high confidence fail), then falls back to URL-based detection for apps like educational games where names aren't displayed (medium confidence).

**SSO missing field handling**
Logs in as a sandbox user with a deliberately sparse profile (missing optional fields like email, last name, etc.). Checks whether the app handles the missing data gracefully or crashes. A crash here typically means the app treats non-guaranteed Clever fields as required.

**SSO session invalidation**
Logs in as User A in one browser context, then logs in as User B in a separate context (simulating a second device). Returns to User A's context and checks whether their session was correctly invalidated. This verifies compliance with Clever's shared device security requirement — every new Clever login must produce a clean session.

---

## Airtable Integration

Vali connects directly to the Clever Secure Sync Airtable base using a personal API token stored in a local `.env` file. No credentials are stored in the codebase.

**What Vali reads from Airtable:**
All fields from the partner's certification form submission, including Redirect URI, Login URL, SSO configuration, sync methods, API version, user roles provisioned, and all free-text responses.

**What Vali writes back to Airtable:**
After each test run, three fields are updated on the partner's row:
- `Vali Status` — overall result (PASS or NEEDS_WORK)
- `Vali Last Run` — timestamp of the most recent run
- `Vali Report` — full JSON report containing every individual test result and detail message

This means any team member can open the Airtable base and see Vali's results alongside the partner's form responses without needing to run the tool themselves.

---

## Dashboard Features

The dashboard runs locally at `http://localhost:5000` and provides:

- **Partner sidebar** — lists all partners from Airtable with color-coded status indicators (green for PASS, red for NEEDS_WORK, amber for not yet tested). Supports search filtering by app name or company name.
- **Test results tab** — shows all test results grouped by category with expandable detail messages for each result. Includes a summary bar showing tests run, passed, failed, and skipped counts.
- **Airtable responses tab** — displays the partner's full certification form responses pulled directly from Airtable, so reviewers never need to switch tools.
- **Re-sync button** — refreshes all partner data from Airtable without losing the current selection or requiring a page refresh.
- **Run tests button** — triggers a full test run for the selected partner. The dashboard polls for completion and updates automatically when results are ready.
- **Export report button** — downloads the full JSON report for the selected partner as a timestamped file.

---

## What Vali Does Not Test (Attestation-Based)

Vali covers the objective, automatable requirements of the certification process. The following requirements are evaluated through partner self-reporting on the certification form and human review by the Clever team:

- **Matching strategy** — how the app matches existing users to Clever records
- **Archive and restore behavior** — how the app handles records deleted or restored in Clever
- **Rollover handling** — how the app manages school year transitions
- **Historical data** — whether student progress data is preserved across record changes
- **Sync logging and alerting** — whether the app has observability into sync failures
- **Retry logic** — whether the app handles transient API failures gracefully
- **Incremental vs full sync** — whether the app uses Clever's Events API for delta syncs

This split is intentional. Vali automates the checks that are hardest to self-report accurately (a partner may not realize they're dropping admin records or mishandling CSRF), while the certification form covers behavioral requirements that partners can accurately describe and that require context to evaluate.

---

## Broader Framework

Vali was designed with a broader ETL framework in mind. A Clever integration is functionally an ETL pipeline — Extract (pull from Clever API), Transform (map to internal schema), Load (write to app database and keep in sync). The certification requirements map to a subset of what any production-ready ETL web app should handle:

| Capability | Vali coverage |
|---|---|
| Primary key consistency | ✅ Automated (duplicate Clever ID check) |
| Role-based data ingestion | ✅ Automated (SSO role coverage test) |
| Graceful handling of missing fields | ✅ Automated (SSO sparse profile test) |
| Session security | ✅ Automated (session invalidation test) |
| OAuth / CSRF protection | ✅ Automated (three OAuth probe tests) |
| API version compliance | ⚠️ Cross-referenced from Airtable form |
| Pagination handling | ⚠️ Partially inferred from role coverage test |
| Archive / restore behavior | 📋 Attestation via certification form |
| Retry logic | 📋 Attestation via certification form |
| Sync observability | 📋 Attestation via certification form |
| Rollover handling | 📋 Attestation via certification form |
| Matching strategy | 📋 Attestation via certification form |

---

## In-Progress Work (Paused)

At the time of pause, the following work was underway:

**Playwright login flow stabilization**
The Clever login flow involves three sequential UI steps before the partner's app is reached: the auth method picker (Badge vs Password), the school picker (district search), and the username/password form. Steps 0 and 1 were working correctly. Step 2 (the login form appearing after district selection) was failing due to a navigation timing issue — Playwright was looking for the username input before the district selection had fully navigated to the district login page. A fix was in progress to wait for `networkidle` after district selection before proceeding to the login form.

**Sandbox user credentials**
The `SANDBOX_USERS` config in `vali_core.py` needs `clever_id`, `district_id`, `username`, and `password` filled in for each sandbox user before SSO tests can run. The `sis_id` values are already populated.

**Sparse profile user**
`SPARSE_USER` in `vali_core.py` needs credentials for a sandbox user with minimal optional fields to enable the missing field handling test.

---

## Setup Requirements

| Requirement | Notes |
|---|---|
| Python 3.8+ | Tested on 3.9 |
| `pip install -r requirements.txt` | Installs Flask, requests, python-dotenv, playwright |
| `playwright install chromium` | Required for SSO browser tests |
| `.env` file | Must contain `AIRTABLE_API_TOKEN`, `AIRTABLE_SECURE_SYNC_BASE_ID`, `AIRTABLE_SECURE_SYNC_TABLE_NAME` |
| Airtable columns | `Vali Status`, `Vali Last Run` (Single line text), `Vali Report` (Long text, plain text — not rich text), `Redirect URI` (Single line text), `Login URL` (Single line text) |
| Sandbox district connected | `#DEMO Certification ISD - Events` must be connected to the partner's Clever app before SSO tests run |

---

## File Reference

| File | Purpose |
|---|---|
| `vali_core.py` | Test engine — all test functions, test registry, shared login helpers |
| `dashboard.py` | Flask web dashboard |
| `airtable_client.py` | Airtable read/write layer |
| `requirements.txt` | Python dependencies |
| `README.md` | Partner-facing setup and usage guide |
| `vali-dev-doc.md` | Public developer documentation page |
| `.env` | Local credentials — never committed to version control |
| `.gitignore` | Should include `.env` |

---

## Contact

For questions about this tool, reach out to the Clever Partnerships / Integrations team at [integrations@clever.com](mailto:integrations@clever.com).