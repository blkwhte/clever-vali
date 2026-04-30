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

    # Check 2: Core Data Ingestion (Did they ingest the Day 1 Edge Cases without crashing?)
    required_ids = EXPECTED_STATE.get("required_clever_ids", [])
    partner_active_sis_ids = [u.get("sis_id") for u in users if u.get("status") == "active" and u.get("sis_id")]
    missing_active = [uid for uid in required_ids if uid not in partner_active_ids]
    
    if missing_active:
        results.append({
            "requirement": "Utilize all relevant data (Edge Case Ingestion)",
            "status": "FAIL",
            "details": f"Missing expected SIS IDs: {missing_active}. App may have crashed on edge cases, or token lacks scope to read sis_id."
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Utilize all relevant data (Edge Case Ingestion)",
            "status": "PASS",
            "details": "All Day 1 edge case records successfully ingested."
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

    with open("certification_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
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