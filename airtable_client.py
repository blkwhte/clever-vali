import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load the .env file so we can read AIRTABLE_API_TOKEN etc.
# without ever hardcoding credentials in source code.
load_dotenv()

# --- CONFIG ---
# These values come from your .env file. If any are missing,
# we raise a clear error right away rather than crashing later
# with a confusing message.
AIRTABLE_API_TOKEN      = os.getenv("AIRTABLE_API_TOKEN")
SECURE_SYNC_BASE_ID     = os.getenv("AIRTABLE_SECURE_SYNC_BASE_ID")
SECURE_SYNC_TABLE_NAME  = os.getenv("AIRTABLE_SECURE_SYNC_TABLE_NAME")

_REQUIRED_ENV = {
    "AIRTABLE_API_TOKEN":           AIRTABLE_API_TOKEN,
    "AIRTABLE_SECURE_SYNC_BASE_ID": SECURE_SYNC_BASE_ID,
    "AIRTABLE_SECURE_SYNC_TABLE_NAME": SECURE_SYNC_TABLE_NAME,
}

def _check_env():
    """Raises a clear error if any required .env value is missing."""
    missing = [k for k, v in _REQUIRED_ENV.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required .env values: {', '.join(missing)}\n"
            "Please check your .env file and try again."
        )

# --- AIRTABLE API HELPERS ---
# Airtable's REST API base URL. All requests go through here.
_BASE_URL = "https://api.airtable.com/v0"

def _headers():
    """Returns the auth headers required by every Airtable API request."""
    return {
        "Authorization": f"Bearer {AIRTABLE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _get_all_records(base_id, table_name):
    """
    Fetches every record from an Airtable table, handling pagination.

    Airtable returns records in pages of up to 100. If there are more,
    the response includes an 'offset' value we pass to the next request
    to get the next page. We keep going until there's no offset left.
    """
    records = []
    url = f"{_BASE_URL}/{base_id}/{requests.utils.quote(table_name)}"
    params = {}

    while True:
        response = requests.get(url, headers=_headers(), params=params, timeout=15)

        if response.status_code != 200:
            raise ConnectionError(
                f"Airtable API error {response.status_code}: {response.text}"
            )

        data = response.json()
        records.extend(data.get("records", []))

        # If there's an offset, there are more pages to fetch.
        offset = data.get("offset")
        if offset:
            params["offset"] = offset
        else:
            break

    return records


def _update_record(base_id, table_name, record_id, fields):
    """
    Updates specific fields on an existing Airtable record.
    Used to write Vali test results back to the partner's row.

    record_id: the Airtable record ID (starts with 'rec')
    fields: a dict of field names and values to update
    """
    url = f"{_BASE_URL}/{base_id}/{requests.utils.quote(table_name)}/{record_id}"
    payload = {"fields": fields}

    response = requests.patch(url, headers=_headers(), json=payload, timeout=15)

    if response.status_code != 200:
        raise ConnectionError(
            f"Airtable update error {response.status_code}: {response.text}"
        )

    return response.json()


# --- PUBLIC INTERFACE ---
# These are the functions the dashboard will actually call.
# They hide all the Airtable API details behind clean, simple names.

def get_all_partners():
    """
    Returns a list of all partner certification submissions from Airtable,
    formatted for the dashboard.

    Each partner dict contains:
      - id:           Airtable record ID (used for writing results back)
      - name:         Company name
      - app_name:     Application name
      - client_id:    Clever development account client ID
      - callback_url: OAuth callback URL (used by Vali's OAuth tests)
      - submitted_at: When the form was submitted
      - fields:       The full set of raw Airtable fields (for the
                      "Airtable responses" tab in the dashboard)
      - vali_status:  Last Vali test result if one has been written back
      - vali_report:  Full JSON report from the last Vali run (if any)
    """
    _check_env()
    records = _get_all_records(SECURE_SYNC_BASE_ID, SECURE_SYNC_TABLE_NAME)

    partners = []
    for record in records:
        fields = record.get("fields", {})
        partners.append({
            "id":           record["id"],
            "name":         fields.get("Company", "Unknown Company"),
            "app_name":     fields.get("App Name", ""),
            "client_id":    fields.get("Dev account Client ID", ""),
            "callback_url": fields.get("Redirect URI", ""),
            "login_url":    fields.get("Login URL", ""),
            "submitted_at": fields.get("Created", record.get("createdTime", "")),
            "fields":       fields,
            "vali_status":  fields.get("Vali Status", "NOT RUN"),
            "vali_report":  _parse_vali_report(fields.get("Vali Report", "")),
        })

    # Sort by submission date, most recent first.
    partners.sort(key=lambda p: p["submitted_at"], reverse=True)
    return partners


def get_partner_by_id(record_id):
    """
    Returns a single partner's data by their Airtable record ID.
    Useful for refreshing one partner's data after running tests.
    """
    _check_env()
    url = f"{_BASE_URL}/{SECURE_SYNC_BASE_ID}/{requests.utils.quote(SECURE_SYNC_TABLE_NAME)}/{record_id}"
    response = requests.get(url, headers=_headers(), timeout=15)

    if response.status_code != 200:
        raise ConnectionError(
            f"Airtable API error {response.status_code}: {response.text}"
        )

    record = response.json()
    fields = record.get("fields", {})

    return {
        "id":           record["id"],
        "name":         fields.get("Company", "Unknown Company"),
        "app_name":     fields.get("App Name", ""),
        "client_id":    fields.get("Dev account Client ID", ""),
        "callback_url": fields.get("Redirect URI", ""),
        "login_url":    fields.get("Login URL", ""),
        "submitted_at": fields.get("Created", record.get("createdTime", "")),
        "fields":       fields,
        "vali_status":  fields.get("Vali Status", "NOT RUN"),
        "vali_report":  _parse_vali_report(fields.get("Vali Report", "")),
    }


def write_vali_results(record_id, overall_status, report):
    """
    Writes Vali test results back to the partner's Airtable row.

    overall_status: "PASS", "NEEDS_WORK", or "FAIL"
    report: the full results list from Vali (will be stored as JSON)

    This creates a permanent record in Airtable so your team can review
    results without needing to re-run Vali or find the local JSON file.
    """
    _check_env()

    # Store the full report as a JSON string in Airtable.
    # We'll parse it back out when loading partner data.
    report_json = json.dumps({
        "overall_status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": report,
    }, indent=2)

    _update_record(
        SECURE_SYNC_BASE_ID,
        SECURE_SYNC_TABLE_NAME,
        record_id,
        {
            # These field names must match your Airtable column names exactly.
            # If they don't exist yet, add them as single-line text fields
            # in your Airtable base before running the dashboard.
            "Vali Status": overall_status,
            "Vali Last Run": datetime.now(timezone.utc).isoformat(),
            "Vali Report": report_json,
        }
    )


def _parse_vali_report(raw):
    """
    Safely parses a Vali report stored as a JSON string in Airtable.
    Returns an empty dict if the field is missing or malformed.
    """
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# --- FIELD NAME MAP ---
# Airtable field names from your certification form, mapped to
# friendly keys used by the dashboard. Update these to match your
# exact Airtable column names if they differ.
#
# To find your exact field names: open your Airtable base, click on
# any column header, and copy the name exactly as it appears.
FIELD_MAP = {
    "Company":                                  "company",
    "App Name":                                 "app_name",
    "Dev account Client ID":                    "client_id",
    "Contact Name":                             "tech_contact_name",
    "Email":                                    "tech_contact_email",
    "Support Contact":                          "support_contact",
    "Application Summary":                      "summary",
    "SSO Support":                              "sso",
    "SSO - Auth Type":                          "sso_auth_type",
    "SSO - Invalidate Previous Sessions":       "sso_invalidate_sessions",
    "SSO - LIWC Button":                        "sso_liwc_button",
    "SSO - Supported User Types":               "sso_user_types",
    "SSO - Loading Behavior":                   "sso_loading_behavior",
    "SSO - Error Handling":                     "sso_error_handling",
    "SSO - Identity Provider":                  "sso_identity_provider",
    "SSO - Supports Hybrid Logins":             "sso_hybrid_logins",
    "Sync Methods":                             "sync_methods",
    "API Version(s)":                           "api_versions",
    "API Versions (v3.0/v3.1)":                "api_versions_v3",
    "Endpoints used":                           "endpoints_used",
    "Which Tokens":                             "tokens_used",
    "User Accounts Provisioned":                "user_roles",
    "Clever ID as Primary ID?":                 "uses_clever_id",
    "Key Identifier from Clever":               "key_identifier",
    "Uses Rosters":                             "uses_rosters",
    "Uses District-App Tokens":                 "uses_district_tokens",
    "Rollover":                                 "rollover",
    "Rollover Period Steps":                    "rollover_steps",
    "Deleted Records":                          "deleted_records",
    "Restoring Records":                        "restoring_records",
    "Deleted Sections":                         "deleted_sections",
    "District Onboarding Steps":                "onboarding_steps",
    "Missing Fields":                           "missing_fields",
    "Required Fields":                          "required_fields",
    "Record Matching":                          "record_matching",
    "Term Data Usage":                          "term_data_usage",
    "Syncs Events":                             "syncs_events",
    "Target Go-Live":                           "go_live_date",
    "Contract Start Date":                      "contract_start_date",
    "Certification Status":                     "cert_status",
    "Not Yet Finished Work":                    "not_finished",
    "Other Integration Information":            "other_info",
    "LMS/CMS":                                  "lms_cms",
    "Tech Stack":                               "tech_stack",
    "Supported Regions":                        "supported_regions",
}


def get_mapped_fields(fields):
    """
    Takes a raw Airtable fields dict and returns a cleaner version
    using the friendly key names from FIELD_MAP above.
    Any fields not in the map are passed through as-is.
    """
    mapped = {}
    for airtable_key, friendly_key in FIELD_MAP.items():
        if airtable_key in fields:
            mapped[friendly_key] = fields[airtable_key]
    return mapped