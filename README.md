# Vali — Clever Secure Sync Validator

Vali is a command-line tool that automatically validates a partner application's Clever Secure Sync integration before it goes live into production. It runs two suites of tests — OAuth security and data ingestion — and produces a timestamped JSON certification report.

Vali is designed to be run by the **partner's development team** on their local machine, against their local development server, before they submit the Clever certification form.

---

## What Vali Tests

Vali covers the technical checks that are objective and automatable. It is designed to complement, not replace, the Clever certification form.

### OAuth Security Tests
These tests probe the partner's Clever callback URL directly to verify it handles bad or malicious requests safely.

| Test | What it checks |
|---|---|
| Missing State Parameter | The app rejects OAuth callbacks that arrive without a `state` parameter |
| Forged State Parameter | The app rejects a `state` value it never issued (CSRF protection) |
| Graceful Code Rejection | The app handles an invalid authorization code without crashing (no 500 errors) |

### Data Ingestion Tests
These tests analyze a JSON file that the partner exports from their application after syncing against the Clever sandbox district.

| Test | What it checks |
|---|---|
| Clever ID as Primary Key | No duplicate Clever IDs exist in the partner's database |
| Edge Case Ingestion | All expected sandbox records are present, including users with short IDs, long IDs, and non-student roles (admins, teachers) |

---

## Requirements

- Python 3.8 or higher
- The `requests` library (`pip install requests`)
- Your Clever dev app is connected with the #DEMO Certification ISD - Events sandbox district; reach out to integrations@clever.com if you're not connected
- Your local development server must be running before you start Vali
- A `diagnostic.json` file exported from your application (see below)

---

## Setup

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/your-org/vali.git
cd vali
pip install requests
```

**2. Start your local development server**

Vali will make real HTTP requests to your callback URL, so your app needs to be running. The default URL Vali expects is:

```
http://localhost:8080/auth/clever/callback
```

If your callback URL is different, you can set it during the setup wizard when you run Vali.

**3. Generate your diagnostic.json file**

Before running Vali, your application needs to sync against **Clever's #DEMO Certification ISD - Events sandbox district** and export a snapshot of the user records it ingested. Save this as `diagnostic.json` in the same folder as `vali.py`.

The file must follow this format:

```json
{
  "users": [
    {
      "clever_id": "abc123",
      "sis_id": "456",
      "status": "active"
    }
  ]
}
```

Every user object must include at minimum a `clever_id` and a `sis_id`. The `status` field is used to determine whether a user is active. Vali supports several common status conventions — see [Active Status Formats](#active-status-formats) below.

---

## Running Vali

```bash
python vali.py
```

Vali will greet you with a short setup wizard:

```
==================================================
🧙 Welcome to the Clever Vali Setup Wizard
==================================================
Run with default settings? (Y/n):
```

**Pressing Enter (or typing Y)** accepts the defaults and runs immediately:
- State parameter checks: **enabled**
- Callback URL: `http://localhost:8080/auth/clever/callback`
- Diagnostic file: `diagnostic.json`

**Typing N** lets you customize each setting before the tests run.

---

## Reading Your Results

After Vali finishes, it prints a summary and saves a full report to a timestamped file in the same directory:

```
certification_report_20260518_155439.json
```

Each result in the report has one of three statuses:

| Status | Meaning |
|---|---|
| `PASS` | This requirement is met. No action needed. |
| `NEEDS_WORK` | Something unexpected happened. Review the details and fix before resubmitting. |
| `FAIL` | This requirement is not met. The details field explains what went wrong and how to fix it. |
| `SKIPPED` | This test was opted out of during setup (e.g. state parameter check when your app doesn't use state). |

The report's `overall_status` is `PASS` only if every test either passed or was intentionally skipped. Any `FAIL` or `NEEDS_WORK` result will set `overall_status` to `NEEDS_WORK`.

### Example Report

```json
{
  "validator_version": "v2.1-ArtifactMode",
  "timestamp": "2026-05-18T15:54:39+00:00",
  "overall_status": "PASS",
  "results": [
    {
      "requirement": "OAuth: Missing State Rejected",
      "status": "PASS",
      "details": "App correctly rejected auth request without state."
    },
    {
      "requirement": "OAuth: Forged State Rejected",
      "status": "PASS",
      "details": "App correctly rejected a state value it never issued."
    },
    {
      "requirement": "OAuth: Graceful Code Rejection",
      "status": "PASS",
      "details": "App safely handled invalid code."
    },
    {
      "requirement": "Use Clever ID as primary identifier",
      "status": "PASS",
      "details": "No duplicate Clever IDs detected."
    },
    {
      "requirement": "Utilize all relevant data (Edge Case Ingestion)",
      "status": "PASS",
      "details": "All Day 1 edge case records successfully ingested."
    }
  ]
}
```

---

## Troubleshooting Common Failures

### OAuth: Missing State Rejected — FAIL
Your app accepted an OAuth callback that had no `state` parameter. The `state` parameter is required for CSRF protection. Every callback your app receives should be rejected if `state` is absent or doesn't match an active session.

### OAuth: Forged State Rejected — FAIL
Your app accepted a `state` value (`VALI_CSRF_PROBE_NOT_A_REAL_SESSION`) that it never issued. Your app must validate the `state` value against its own session store on every callback — not just check that *some* state was present.

### OAuth: Graceful Code Rejection — FAIL (500 error)
Your app crashed when Clever rejected the invalid authorization code. Add error handling around your token exchange step so that a rejected code results in a clean redirect or error page, not a server crash.

### Edge Case Ingestion — FAIL
One or more expected sandbox users were not found in your `diagnostic.json`. The failure message will tell you exactly which users are missing and what roles they belong to. Common causes:

- **Pagination:** Your app only fetched the first page of results from the Clever API. Make sure you follow `next` links until all pages are retrieved.
- **Role filtering:** If all missing records share the same role (e.g. all admins), your app may be skipping that role entirely. Check your ingestion logic and token scopes.
- **Active status:** Confirm the missing users are marked active in your system.
- **Token scope:** Ensure your Clever API token has permission to read `sis_id` for all user types.

You can read more about what edge cases are tested on this page of the Clever Dev Docs: https://dev.clever.com/docs/sync-testing#testing-with-certification-isd

---

## Active Status Formats

Vali understands several common ways applications represent whether a user is active. You don't need to change your data format — Vali will detect whichever convention your app uses:

| Field | How Vali interprets it |
|---|---|
| `"status": "active"` | Standard string status |
| `"is_active": true` | Boolean active flag |
| `"is_archived": false` | Boolean archive flag (inverted) |
| `"deleted_at": null` | Soft-delete timestamp — null means active |
| *(no status field)* | Assumed active if the user was included in the export |

---

## What Vali Does Not Test

Vali covers the objective, automatable requirements of the Clever certification process. The following areas require human review via the Clever certification form and are out of scope for Vali:

- Session invalidation on shared devices
- School year rollover handling
- Deleted and restored record behavior
- District onboarding steps and sync ownership
- Admin permission handling
- Application icon, supported regions, and other intake fields

These are evaluated by the Clever team as part of the standard certification review after you submit the form.

---

## Submitting Your Report

Once Vali shows `overall_status: PASS`, include your `certification_report_*.json` file when you submit the Clever Secure Sync Certification Form. This lets the Clever team verify your technical checks were completed and speeds up the review process.

If you have questions about a failure you can't resolve, reach out to [integrations@clever.com](mailto:integrations@clever.com).

---

## For Clever Team Members

### How the sandbox tests work

Vali checks the partner's diagnostic file against a fixed set of records from the Clever sandbox district (`EXPECTED_STATE` in `vali.py`). These are real records in the sandbox and are intentionally chosen to cover edge cases:

- Users with long numeric SIS IDs (potential truncation bugs)
- Users with very short SIS IDs (potential type mismatch bugs)
- Non-student roles: one admin, one teacher (catches role-filtering bugs)

### Adding new sandbox test cases

To add a new required user to the edge case suite, add an entry to the `required_users` list in `EXPECTED_STATE` at the top of `vali.py`:

```python
{"sis_id": "YOUR_SIS_ID", "name": "Display Name", "role": "student"}  # or "teacher" / "admin"
```

The `role` field is used to generate targeted error messages when that user is missing, so make sure it accurately reflects the user's role in the sandbox district.

### Versioning

The report includes a `validator_version` field. When making changes that affect test behavior or grading logic, increment the version string in `generate_report()` so Clever can identify which version of Vali produced a given report.
