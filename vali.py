import requests
import json
from datetime import datetime
import sys
import os
from dotenv import load_dotenv, find_dotenv

# find_dotenv() aggressively searches your directory tree for the .env file
load_dotenv(find_dotenv())

# ---------------------------------------------------------
# THE GOLDEN STATE (What Vali knows is in the Clever Sandbox)
# ---------------------------------------------------------
# As the Clever expert, you can expand this later. For v1, 
# we expect the partner to have ingested 2 active users and 
# archived 1 user that was previously unshared.
EXPECTED_STATE = {
    "expected_active_ids": ["clever_stu_001", "clever_tch_002"],
    "expected_archived_ids": ["clever_stu_003"] # Unshared student
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
    users = partner_data.get("users", [])
    if not users:
        return [{"requirement": "Diagnostic Endpoint Schema", "status": "FAIL", "details": "No 'users' array found in the response."}], False

    # Extract Partner State
    partner_active_ids = [u.get("clever_id") for u in users if u.get("status") == "active"]
    partner_archived_ids = [u.get("clever_id") for u in users if u.get("status") == "archived"]

    # Check 2: Core Data Ingestion (Did they get the active users?)
    missing_active = [uid for uid in EXPECTED_STATE["expected_active_ids"] if uid not in partner_active_ids]
    if missing_active:
        results.append({
            "requirement": "Utilize all relevant data (Ingestion)",
            "status": "FAIL",
            "details": f"Missing expected active Clever IDs: {missing_active}"
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Utilize all relevant data (Ingestion)",
            "status": "PASS",
            "details": "All expected active Clever IDs successfully ingested."
        })

    # Check 3: Archival Logic (Did they archive instead of hard-delete?)
    missing_archived = [uid for uid in EXPECTED_STATE["expected_archived_ids"] if uid not in partner_archived_ids]
    if missing_archived:
        results.append({
            "requirement": "Archive unshared records",
            "status": "FAIL",
            "details": f"Expected Clever IDs to be archived, but missing: {missing_archived}. Check if app hard-deleted them."
        })
        overall_pass = False
    else:
        results.append({
            "requirement": "Archive unshared records",
            "status": "PASS",
            "details": "Successfully archived unshared Clever IDs."
        })

    # Check 4: Primary Key Usage (No duplicates)
    # If the partner has multiple entries for the same Clever ID, they aren't using it as the Primary Key
    all_partner_ids = [u.get("clever_id") for u in users]
    if len(all_partner_ids) != len(set(all_partner_ids)):
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