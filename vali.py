import requests
import json
from datetime import datetime
import sys
import os
from dotenv import load_dotenv, find_dotenv

# find_dotenv() aggressively searches your directory tree for the .env file
load_dotenv(find_dotenv())

# ---------------------------------------------------------
# THE GOLDEN STATE (Day 1: Baseline Ingestion)
# ---------------------------------------------------------
EXPECTED_STATE = {
    "required_clever_ids": [
        "738733110", # Long Username Test (Scenario 26)
        "841688312", # No Username Test (Scenario 31)
        "48",        # Quote in Email Test (Scenario 8)
        "69",        # Missing @ in Email Test (Scenario 9)
        "4",         # Admin in Mult-Schools (Scenario 3)
        "50"         # Teacher without Enrollment (Scenario 18)
    ],
    "numeric_sections": ["581", "582"] # Nonsense Names (Scenario 4)
}

def fetch_diagnostic_data(endpoint_url):
    """Hits the partner's standardized diagnostic endpoint."""
    try:
        print(f"[*] Fetching diagnostic data from: {endpoint_url}")
        response = requests.get(endpoint_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[!] Failed to reach endpoint: {e}")
        return None

def evaluate_integration(partner_data):
    """Runs the validation checks against the partner's data."""
    results = []
    overall_pass = True

    # Check 1: Did they actually return a user array?
    # (Using 'is None' because an empty list [] is technically a valid response if the DB is empty)
    users = partner_data.get("users")
    if users is None:
        return [{"requirement": "Diagnostic Endpoint Schema", "status": "FAIL", "details": "No 'users' array found in the response."}], False

    # Extract Partner State
    partner_active_ids = [u.get("clever_id") for u in users if u.get("status") == "active"]
    partner_archived_ids = [u.get("clever_id") for u in users if u.get("status") == "archived"]

    # Check 2: Core Data Ingestion (Using SIS ID now!)
    # Force all expected IDs to strings and strip whitespace to prevent type mismatches
    required_ids = [str(uid).strip() for uid in EXPECTED_STATE.get("required_clever_ids", [])]
    
    # Safely extract partner IDs, forcing to string and stripping whitespace
    partner_active_sis_ids = []
    for u in users:
        if u.get("status") == "active" and u.get("sis_id"):
            partner_active_sis_ids.append(str(u.get("sis_id")).strip())
    
    missing_active = [uid for uid in required_ids if uid not in partner_active_sis_ids]
    
    if missing_active:
        # SMART MESSAGING: Actionable, human-readable feedback
        details = (
            f"Missing Expected SIS IDs: {missing_active}\n\n"
            f"🔍 Vali Debugger:\n"
            f"Vali checked the 'sis_id' field for users with 'status': 'active'.\n"
            f"Your diagnostic endpoint successfully returned {len(partner_active_sis_ids)} users with a valid sis_id, "
            f"but the edge cases listed above were not found among them.\n\n"
            f"🛠️ How to fix:\n"
            f"  1. Pagination Pitfall: Did your app fetch ALL pages of data? Clever API v3.0 paginates at 100 records. "
            f"If your endpoint returns fewer users than expected, ensure your sync engine follows the 'next' links in the API response.\n\n"
            f"  2. Ingestion Rejection: Did your app skip them? These specific IDs test edge cases (e.g., missing emails, long usernames). "
            f"Check your app's sync logs to see if they crashed your database schema.\n\n"
            f"  3. Active Status: Are they marked correctly? Ensure your diagnostic endpoint is returning 'status': 'active' for these users.\n\n"
            f"  4. Token Scope: Ensure your app's Clever token actually has permission to read the 'sis_id' field."
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

    # Check 3: Primary Identifier Usage (No duplicates)
    all_partner_clever_ids = [u.get("clever_id") for u in users if u.get("clever_id")]
    if len(all_partner_clever_ids) != len(set(all_partner_clever_ids)):
        results.append({
            "requirement": "Use Clever ID as primary identifier",
            "status": "FAIL",
            "details": "Duplicate Clever IDs found. App is likely using email or name as primary key."
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Use Clever ID as primary identifier",
            "status": "PASS",
            "details": "No duplicate Clever IDs detected."
        })

    return results, overall_pass

def generate_report(results, overall_pass):
    """Outputs the JSON report card."""
    report = {
        "validator_version": "v1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "overall_status": "PASS" if overall_pass else "NEEDS_WORK",
        "results": results
    }

    with open("certification_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*40)
    print(f"VALIDATION COMPLETE: {report['overall_status']}")
    print("Report saved to -> certification_report.json")
    print("="*40)

if __name__ == "__main__":
    # Grab the endpoint from the .env file, or default to localhost:8080 if not found
    partner_endpoint = os.getenv("PARTNER_ENDPOINT", "http://localhost:8080/_clever_diagnostic")
    
    data = fetch_diagnostic_data(partner_endpoint)
    
    if data:
        validation_results, passed = evaluate_integration(data)
        generate_report(validation_results, passed)
    else:
        print("[!] Cannot generate report without diagnostic data.")
        sys.exit(1)
        