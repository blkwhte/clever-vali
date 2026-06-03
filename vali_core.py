import os
import sys
import json
import time
import random
import requests

# FIX 7: Replaced deprecated datetime.utcnow() with the modern timezone-aware version.
# The old way still works today but Python 3.12+ warns you about it, and it will
# eventually be removed. This is the future-proof replacement.
from datetime import datetime, timezone

# --- DAY 1 EXPECTED STATE ---
# These IDs point to specific records in the Clever sandbox district.
# They are intentionally hardcoded because the sandbox is a fixed environment
# your team controls. The key is renamed below for clarity (see FIX 4).
#
# FUTURE: If this list grows large, consider moving it to expected_state.json
# and loading it at startup (see FIX 8 note at bottom of file).
EXPECTED_STATE = {
    # Each entry is a dict with three fields:
    #   sis_id  — the value Vali looks for in the partner's diagnostic file
    #   name    — the sandbox user's display name (for human-readable error output)
    #   role    — the Clever role: "student", "teacher", or "admin"
    #
    # Having the role here lets Vali tell partners *why* a record is missing,
    # not just *which* one — e.g. "all missing records are admins" points straight
    # to a role-filtering bug or a missing token scope.
    "required_users": [
        {"sis_id": "738733110", "name": "Diane Schmeler", "role": "student"},
        {"sis_id": "841688312", "name": "Kim Schmeler",   "role": "student"},
        {"sis_id": "48",        "name": "Haylie Hauck",   "role": "student"},
        {"sis_id": "69",        "name": "Seth Schoen",    "role": "student"},
        {"sis_id": "4",         "name": "Admin 4",        "role": "admin"},
        {"sis_id": "50",        "name": "Teacher 50",     "role": "teacher"},
    ]
}

# FIX 2: Maximum allowed file size for the diagnostic JSON.
# Without this, a partner could accidentally hand us a huge file and crash
# the process. 50 MB is generous for a user roster JSON.
MAX_FILE_SIZE_MB = 50


def interactive_setup():
    print("="*50)
    print("🧙‍♂️ Welcome to the Clever Vali Setup Wizard")
    print("="*50)

    use_defaults = input("Run with default settings? (Y/n): ").strip().lower()
    if use_defaults == 'y' or use_defaults == '':
        return {
            "use_state": True,
            "callback_url": "http://localhost:8080/auth/clever/callback",
            "data_file": "diagnostic.json"
        }

    print("\nLet's customize your test suite:")

    state_input = input("1. Does your app use the 'state' parameter for CSRF protection? (Y/n): ").strip().lower()
    use_state = True if state_input in ['y', ''] else False

    default_url = "http://localhost:8080/auth/clever/callback"
    url_input = input(f"2. What is your local Clever callback URL? [{default_url}]: ").strip()
    callback_url = url_input if url_input else default_url

    default_file = "diagnostic.json"
    file_input = input(f"3. Path to your diagnostic JSON file? [{default_file}]: ").strip()
    data_file = file_input if file_input else default_file

    return {
        "use_state": use_state,
        "callback_url": callback_url,
        "data_file": data_file
    }

def _get_with_backoff(url, max_retries=3, base_delay=1.0, **kwargs):
    """
    Makes a GET request with exponential backoff and jitter on 429 responses.

    If the server returns 429 (Too Many Requests), we wait and retry
    rather than immediately failing the test. The wait doubles each
    attempt, with a small random offset (jitter) so retries from
    multiple tools don't all fire at the same instant.

    Wait times: ~1s, ~2s, ~4s before giving up.

    Any non-429 response (including errors) is returned immediately
    without retrying — backoff is only for rate limiting, not other issues.
    """
    for attempt in range(max_retries):
        response = requests.get(url, **kwargs)

        if response.status_code != 429:
            return response

        if attempt < max_retries - 1:
            # Exponential backoff: 1s, 2s, 4s — plus up to 0.5s of random jitter.
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            print(f"   [!] Rate limited (429). Retrying in {delay:.1f}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)

    # All retries exhausted — return the last 429 response so the
    # calling test can handle it and report it clearly.
    return response

def test_oauth_security(config):
    print("\n" + "="*40)
    print("🛡️ RUNNING OAUTH SECURITY TESTS")
    print("="*40)

    callback_url = config['callback_url']
    results = []

    # TEST 1: Missing State Parameter (CONDITIONAL)
    if config['use_state']:
        print("[TEST] Missing State Parameter...")
        try:
            # FIX 9: Added timeout=10 to all requests calls.
            # Without a timeout, if the partner's server hangs, this tool hangs
            # with it — forever. 10 seconds is plenty for a local server to respond.
            response = _get_with_backoff(
                f"{callback_url}?code=fake_code_123",
                allow_redirects=False,
                timeout=10
            )
            if response.status_code == 429:
                results.append({"requirement": "OAuth: Missing State Rejected", "status": "NEEDS_WORK", "details": "Server returned 429 (rate limited) after all retries. Try again in a few minutes."})
            elif response.status_code in [400, 401, 403]:
                results.append({"requirement": "OAuth: Missing State Rejected", "status": "PASS", "details": "App correctly rejected auth request without state."})
            else:
                results.append({"requirement": "OAuth: Missing State Rejected", "status": "FAIL", "details": f"Expected 400/401/403, got {response.status_code}"})
        except requests.exceptions.Timeout:
            results.append({"requirement": "OAuth: Missing State Rejected", "status": "FAIL", "details": "Server did not respond within 10 seconds."})
        except requests.exceptions.RequestException:
            results.append({"requirement": "OAuth: Missing State Rejected", "status": "FAIL", "details": "Server crashed or unreachable."})
    else:
        results.append({"requirement": "OAuth: Missing State Rejected", "status": "SKIPPED", "details": "Developer opted out of state parameter check."})

    # TEST 2: Forged/Invalid State Parameter (CONDITIONAL)
    # FIX 1: The original code sent &state=fake_session_state, which is ambiguous.
    # A broken app might accept ANY state string, making this test pass incorrectly.
    # We now send a value that is clearly probe-originated and document the intent:
    # the app must reject a state value it never issued. This is a stronger signal.
    if config['use_state']:
        print("[TEST] Forged State Parameter...")
        try:
            forged_state_url = f"{callback_url}?code=fake_code_123&state=VALI_CSRF_PROBE_NOT_A_REAL_SESSION"
            response = _get_with_backoff(forged_state_url, allow_redirects=False, timeout=10)
            if response.status_code == 429:
                results.append({"requirement": "OAuth: Forged State Rejected", "status": "NEEDS_WORK", "details": "Server returned 429 (rate limited) after all retries. Try again in a few minutes."})
            elif response.status_code in [400, 401, 403]:
                results.append({"requirement": "OAuth: Forged State Rejected", "status": "PASS", "details": "App correctly rejected a state value it never issued."})
            else:
                results.append({"requirement": "OAuth: Forged State Rejected", "status": "FAIL", "details": f"App accepted a forged state value (status {response.status_code}). State must be validated against active sessions."})
        except requests.exceptions.Timeout:
            results.append({"requirement": "OAuth: Forged State Rejected", "status": "FAIL", "details": "Server did not respond within 10 seconds."})
        except requests.exceptions.RequestException:
            results.append({"requirement": "OAuth: Forged State Rejected", "status": "FAIL", "details": "Server crashed or unreachable."})

    # TEST 3: Invalid Authorization Code (Universal)
    print("[TEST] Invalid Authorization Code...")
    try:
        test_url = f"{callback_url}?code=invalid_forged_code_999"
        if config['use_state']:
            test_url += "&state=VALI_CSRF_PROBE_NOT_A_REAL_SESSION"

        response = _get_with_backoff(test_url, allow_redirects=False, timeout=10)

        if response.status_code == 429:
            results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "NEEDS_WORK", "details": "Server returned 429 (rate limited) after all retries. Try again in a few minutes."})
        elif response.status_code in [302, 303, 400, 401]:
            results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "PASS", "details": "App safely handled invalid code."})
        elif response.status_code == 500:
            results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "FAIL", "details": "App crashed (500) when Clever rejected the code. Add error handling!"})
        else:
            results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "NEEDS_WORK", "details": f"Unexpected status {response.status_code}."})
    except requests.exceptions.Timeout:
        results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "FAIL", "details": "Server did not respond within 10 seconds."})
    except requests.exceptions.RequestException:
        results.append({"requirement": "OAuth: Graceful Code Rejection", "status": "FAIL", "details": "Server crashed."})

    for r in results:
        print(f" -> {r['requirement']}: {r['status']}")

    return results


def load_diagnostic_data(filepath):
    """Loads and validates data from the local JSON artifact."""
    if not os.path.exists(filepath):
        print(f"\n[!] Error: Could not find '{filepath}'.")
        print("Please ensure your application generated the diagnostic dump before running Vali.")
        # FIX 6: Print the expected file format so partners know exactly what to produce.
        # This replaces a frustrating trial-and-error experience with a clear spec.
        print("\nExpected JSON format:")
        print('  { "users": [ { "clever_id": "...", "sis_id": "...", "status": "active" } ] }')
        return None

    # FIX 2: Check the file size before trying to load it into memory.
    # os.path.getsize() returns bytes, so we divide to get megabytes.
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        print(f"\n[!] Error: '{filepath}' is {size_mb:.1f} MB — exceeds the {MAX_FILE_SIZE_MB} MB limit.")
        print("Please ensure you are pointing to the correct diagnostic file.")
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"\n[!] Error: '{filepath}' contains invalid JSON.")
            print('Expected format: { "users": [ { "clever_id": "...", "sis_id": "...", "status": "active" } ] }')
            return None

    # FIX 3: Validate the structure of the loaded data before we try to use it.
    # Previously, if "users" was missing or wasn't a list, the code would crash
    # deep inside evaluate_integration() with a confusing error message.
    # Now we catch it here with a clear, actionable message.
    if not isinstance(data, dict):
        print("\n[!] Error: JSON file must be an object (starts with '{'), not a list or other type.")
        return None

    users = data.get("users")

    if users is None:
        print("\n[!] Error: JSON file is missing a 'users' key.")
        print('Expected format: { "users": [ ... ] }')
        return None

    if not isinstance(users, list):
        print("\n[!] Error: 'users' must be a list (array) of user objects.")
        return None

    # Filter out any entries that aren't dictionaries (defensive, just in case).
    valid_users = [u for u in users if isinstance(u, dict)]
    skipped = len(users) - len(valid_users)
    if skipped > 0:
        print(f"[!] Warning: Skipped {skipped} malformed user entries (not objects).")

    # Return a cleaned-up version of the data with only valid user entries.
    data["users"] = valid_users
    return data


def is_user_active(user):
    """
    Flexibly determines if a user is active based on multiple industry-standard database schemas.
    """
    # 1. The String Status (Our original method)
    if "status" in user and user["status"] != "":
        return str(user["status"]).strip().lower() == "active"

    # 2. The Boolean Active Flag
    if "is_active" in user:
        return bool(user["is_active"])

    # 3. The Boolean Archive Flag
    if "is_archived" in user:
        return not bool(user["is_archived"])

    # 4. Soft Delete Timestamp (If it has a timestamp, they are deleted/archived)
    if "deleted_at" in user:
        return user["deleted_at"] is None or str(user["deleted_at"]).strip() == ""

    # Default: If the partner included them in the JSON and provided no status flags,
    # we have to assume they are treating them as an active user.
    return True


def evaluate_integration(data):
    """Evaluates the payload against certification requirements."""
    results = []
    overall_pass = True
    users = data.get("users", [])

    # Check 1: Primary Key Architecture
    clever_ids = [u.get("clever_id") for u in users if u.get("clever_id")]
    if len(clever_ids) != len(set(clever_ids)):
        results.append({
            "requirement": "Use Clever ID as primary identifier",
            "status": "FAIL",
            "details": "Duplicate Clever IDs detected. App is likely using email or SIS ID as the primary key."
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Use Clever ID as primary identifier",
            "status": "PASS",
            "details": "No duplicate Clever IDs detected."
        })

    # Check 2: Core Data Ingestion (Edge Cases)
    # EXPECTED_STATE now stores each required user as a dict with sis_id, name, and role.
    # We build a lookup of the partner's active SIS IDs once, then check each expected
    # user against it individually so we can report exactly who is missing and what role
    # they belong to.
    required_users = EXPECTED_STATE.get("required_users", [])
    partner_active_sis_ids = {
        str(u.get("sis_id")).strip()
        for u in users
        if is_user_active(u) and u.get("sis_id")
    }

    # Find which expected users are absent from the partner's file.
    missing_users = [
        ru for ru in required_users
        if str(ru["sis_id"]).strip() not in partner_active_sis_ids
    ]

    if missing_users:
        # Group missing users by role so the error message highlights patterns
        # (e.g. "all missing records are admins") rather than just listing IDs.
        by_role = {}
        for ru in missing_users:
            by_role.setdefault(ru["role"], []).append(ru)

        missing_lines = []
        for role, records in sorted(by_role.items()):
            for r in records:
                missing_lines.append(f"  - [{role.upper()}] {r['name']} (sis_id: {r['sis_id']})")

        # Build a role-specific hint if all missing records share the same role.
        if len(by_role) == 1:
            sole_role = list(by_role.keys())[0]
            role_hint = (
                f"  ⚠️  All missing records are role='{sole_role}'. "
                f"This often means your app is filtering out {sole_role}s entirely, "
                f"or your token lacks the scope to read them.\n"
            )
        else:
            roles_affected = ", ".join(sorted(by_role.keys()))
            role_hint = f"  ⚠️  Missing records span multiple roles: {roles_affected}.\n"

        details = (
            f"Missing {len(missing_users)} of {len(required_users)} expected sandbox records:\n"
            + "\n".join(missing_lines) + "\n\n"
            + f"🔍 Vali Debugger:\n"
            + role_hint
            + f"  Your file contains {len(partner_active_sis_ids)} active users with a valid sis_id.\n\n"
            + f"🛠️ How to fix:\n"
            + f"  1. Pagination Pitfall: Did your app fetch ALL pages of data?\n"
            + f"  2. Role Filtering: Is your app ignoring certain roles (student/teacher/admin)?\n"
            + f"  3. Ingestion Rejection: Did your app skip them? Check your logs.\n"
            + f"  4. Active Status: Are they marked active?\n"
            + f"  5. Token Scope: Ensure your Clever token can read 'sis_id' for all roles."
        )
        results.append({
            "requirement": "Utilize all relevant data (Edge Case Ingestion)",
            "status": "FAIL",
            "details": details
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Utilize all relevant data (Edge Case Ingestion)",
            "status": "PASS",
            "details": "All Day 1 edge case records successfully ingested. Robust error handling verified!"
        })

    return results, overall_pass


def generate_report(oauth_results, data_results, overall_pass):
    """Outputs the JSON report card."""
    combined_results = oauth_results + data_results

    # FIX 10: Timestamp the output filename so each run produces a unique file.
    # Previously, running Vali twice would silently overwrite the first report.
    # Now partners keep a full history of every validation run.
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"certification_report_{timestamp_str}.json"

    report = {
        "validator_version": "v2.1-ArtifactMode",
        # FIX 7: datetime.now(timezone.utc) replaces the deprecated datetime.utcnow().
        # Both produce a UTC timestamp, but this version is explicit about the timezone
        # and won't trigger deprecation warnings in Python 3.12+.
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # FIX 5: overall_status now correctly treats NEEDS_WORK as a failure.
        # Previously, a NEEDS_WORK result from an OAuth test would silently pass
        # the overall grade. Now any non-PASS, non-SKIPPED result fails the run.
        "overall_status": "PASS" if overall_pass else "NEEDS_WORK",
        "results": combined_results
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "="*40)
    print(f"VALIDATION COMPLETE: {report['overall_status']}")
    print(f"Report saved to -> {filename}")
    print("="*40)


if __name__ == "__main__":
    # 1. Ask the developer how they want to test
    config = interactive_setup()

    # 2. Run OAuth security tests against the live callback URL
    oauth_results = test_oauth_security(config)

    # 3. Grade the Data Ingestion from the diagnostic file
    print("\n" + "="*40)
    print("📊 RUNNING DATA INGESTION TESTS")
    print("="*40)

    data = load_diagnostic_data(config['data_file'])
    if data:
        data_results, data_passed = evaluate_integration(data)

        # FIX 5: Updated overall pass/fail logic to treat NEEDS_WORK as a failure.
        # The original code only checked for PASS and SKIPPED, which meant a
        # NEEDS_WORK result from an OAuth test would be silently ignored.
        failing_statuses = {'FAIL', 'NEEDS_WORK'}
        oauth_passed = not any(r['status'] in failing_statuses for r in oauth_results)
        overall_pass = data_passed and oauth_passed

        generate_report(oauth_results, data_results, overall_pass)
    else:
        print("[!] Validation aborted. Fix the data file issue and run Vali again.")
        sys.exit(1)

# --- FIX 8 NOTE: Scaling EXPECTED_STATE ---
# Right now the sandbox IDs live inline above. If the list grows large,
# you can move them to a separate file called expected_state.json and
# replace the EXPECTED_STATE block at the top with this:
#
#   with open("expected_state.json", "r") as f:
#       EXPECTED_STATE = json.load(f)
#
# expected_state.json would look like:
#   {
#     "required_sis_ids": ["738733110", "841688312", "48", "69", "4", "50"]
#   }
#
# That file stays in your repo and partners never touch it.