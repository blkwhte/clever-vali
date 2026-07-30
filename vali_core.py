import os
import sys
import json
import time
import random
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# SANDBOX CONFIG
# ---------------------------------------------------------------------------
# These users live in the #DEMO Certification ISD - Events sandbox district.
# Each entry has the Clever credentials Playwright uses to log in, plus
# metadata used for result reporting.
#
# CREDENTIALS: stored here for internal use only. This file should never
# be committed to a public repo. Add vali_core.py to .gitignore if needed,
# or move credentials to .env (see bottom of file for how).
# Each sandbox user has two identifiers:
#   clever_id — the Clever-assigned UUID for this record. This is the stable
#               primary key your duplicate check relies on.
#   sis_id    — the district-assigned Student Information System ID. We check
#               this to verify the district isn't passing duplicate records to
#               Clever. These are the values your team hardcoded previously.
#
# Both fields are required. If a partner's app is using sis_id as their
# primary key instead of clever_id, the duplicate check will catch it.
SANDBOX_USERS = [
    {
        "clever_id":   "58da8c65d7dc0ca0680006b6",
        "sis_id":      "738733110",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Diane Schmeler",
        "role":        "student",
        "username":    "738733110",
        "password":    "738733110",
    },
    {
        "clever_id":   "58da8c65d7dc0ca06800071f",
        "sis_id":      "841688312",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Kim Schmeler",
        "role":        "student",
        "username":    "841688312",
        "password":    "841688312",
    },
    {
        "clever_id":   "5faac8b7bc447500a10ae841",
        "sis_id":      "48",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Haylie Hauck",
        "role":        "teacher",
        "username":    "830340",
        "password":    "830340",
    },
    {
        "clever_id":   "5faac8b7bc447500a10ae87f",
        "sis_id":      "69",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Seth Schoen",
        "role":        "teacher",
        "username":    "256742",
        "password":    "256742",
    },
    {
        "clever_id":   "5faac8b7bc447500a10ae89c",
        "sis_id":      "4",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Emily Smyth",
        "role":        "admin",
        "username":    "esmyth@example.com",
        "password":    "4",
    },
    {
        "clever_id":   "5faac8b7bc447500a10ae843",
        "sis_id":      "50",
        "district_id": "58da8a43cc70ab00017a1a87",
        "name":        "Rupert Doyle",
        "role":        "teacher",
        "username":    "473664",
        "password":    "473664",
    },
]

# One sparse-profile user for the missing field handling test.
# This user has minimal optional fields set in the sandbox to test
# whether the partner app handles missing non-required fields gracefully.
SPARSE_USER = {
    "clever_id":   "58da8c63d7dc0ca0680003ed",
    "sis_id":      "100095233",
    "district_id": "58da8a43cc70ab00017a1a87",
    "name":        "Sparse Test User",
    "role":        "student",
    "username":    "100095233",
    "password":    "100095233",
}

MAX_FILE_SIZE_MB = 50


# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------

def _result(requirement, status, details, category="General"):
    """
    Returns a standardised result dict.
    Every test function returns one of these — the registry runner
    collects them all into the final report.
    """
    return {
        "requirement": requirement,
        "status":      status,       # PASS | FAIL | NEEDS_WORK | SKIPPED
        "details":     details,
        "category":    category,
    }


def _get_with_backoff(url, max_retries=3, base_delay=1.0, **kwargs):
    """
    GET with exponential backoff + jitter on 429 responses.
    Any non-429 response is returned immediately.
    """
    for attempt in range(max_retries):
        response = requests.get(url, **kwargs)
        if response.status_code != 429:
            return response
        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            print(f"   [!] Rate limited (429). Retrying in {delay:.1f}s... "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
    return response


def _click_password_card(page):
    """
    Clicks the Password card on Clever's auth method picker (Badge | Password).
    Called at two points in the login flow — once at schools.clever.com and
    once after district selection on the district's own auth page.
    Returns True if the card was found and clicked, False if not present.
    """
    selectors = [
        'a[aria-label="Password"]',
        'a:has-text("Password")',
        '[class*="AuthMethodCard"]:has-text("Password")',
    ]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=4000)
            page.click(selector)
            page.wait_for_load_state("domcontentloaded", timeout=8000)
            return True
        except Exception:
            continue
    return False


def _clever_login(page, username, password, district_id=""):
    """
    Drives Playwright through Clever's login flow (as of July 2026):

    Step 1 — Auth method picker: schools.clever.com shows Badge | Password.
              Vali clicks Password.

    Step 2 — School picker: type district ID, wait for suggestion card,
              click it. Clever navigates to the district login page.

    Step 3 — Username form: enter username, click Next.

    Step 4 — Password form (separate page): enter password, click Next.

    Step 5 — Wait for redirect back to the partner app.

    Returns True if login completed successfully, False otherwise.
    """
    try:
        # Step 1: Auth method picker — click Password card.
        print(f"   [SSO] Step 1: Looking for auth method picker...")
        password_card_selectors = [
            'a[aria-label="Password"]',
            'a:has-text("Password")',
            '[class*="AuthMethodCard"]:has-text("Password")',
        ]
        for selector in password_card_selectors:
            try:
                page.wait_for_selector(selector, timeout=5000)
                page.click(selector)
                page.wait_for_load_state("domcontentloaded", timeout=8000)
                print(f"   [SSO] Password card clicked. URL: {page.url}")
                break
            except Exception:
                continue

        # Step 2: School picker — type district ID and click the suggestion.
        if district_id:
            print(f"   [SSO] Step 2: Looking for school picker... (current URL: {page.url})")
            # Wait explicitly for the school-picker URL before looking for the input.
            # This ensures we're on the right page before any selector search begins.
            try:
                page.wait_for_url(lambda url: "school-picker" in url, timeout=8000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            print(f"   [SSO] School picker URL confirmed: {page.url}")
            picker_selectors = [
                'input[title="School name"]',
                'input[aria-labelledby="school-picker-heading"]',
                'input[class*="Autosuggest"]',
                'input[placeholder*="school" i]',
            ]
            picker_input = None
            for selector in picker_selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    picker_input = selector
                    break
                except Exception:
                    continue

            if not picker_input:
                screenshot_path = f"vali_picker_debug_{district_id[:8]}.png"
                page.screenshot(path=screenshot_path)
                raise Exception(
                    f"School picker input not found. "
                    f"Screenshot saved to {screenshot_path}"
                )

            print(f"   [SSO] School picker found. Typing district ID...")
            page.click(picker_input)
            page.fill(picker_input, "")
            # type() fires real keystroke events which trigger the React
            # autocomplete. delay=80ms mimics human typing pace.
            page.type(picker_input, district_id, delay=80)

            # Wait for the suggestion card then click it.
            suggestion_selectors = [
                '[id^="react-autowhatever-"] li',
                'li[id*="item-0"]',
                '.Autosuggest--suggestion',
                '[role="option"]',
            ]
            # Wait for the suggestion to appear, then click it.
            # We wait for the element to be visible and stable before clicking.
            suggestion_selectors_ordered = [
                f'[id^="react-autowhatever-"] li:has-text("{district_id}")',
                f'[role="option"]:has-text("{district_id}")',
                '[id^="react-autowhatever-"] li:first-child',
                'li[id*="item-0"]',
                '.Autosuggest--suggestion',
                '[role="option"]',
            ]
            suggestion_clicked = False
            for sel in suggestion_selectors_ordered:
                try:
                    page.wait_for_selector(sel, timeout=6000)
                    # Small delay to let the suggestion card fully render
                    # before clicking — React can still be updating state.
                    page.wait_for_timeout(500)
                    # Scroll into view and click via JavaScript to ensure
                    # the click lands on the element regardless of overlays.
                    element = page.query_selector(sel)
                    if element:
                        element.scroll_into_view_if_needed()
                        element.click()
                        suggestion_clicked = True
                        print(f"   [SSO] District suggestion clicked via selector: {sel}")
                        break
                except Exception:
                    continue

            if not suggestion_clicked:
                screenshot_path = f"vali_picker_debug_{district_id[:8]}.png"
                page.screenshot(path=screenshot_path)
                raise Exception(
                    f"District suggestion never appeared for ID '{district_id}'. "
                    f"Screenshot saved to {screenshot_path}"
                )

            # Wait explicitly for the URL to change away from school-picker.
            # This is the definitive signal that the district was selected.
            print(f"   [SSO] Waiting for navigation away from school-picker...")
            try:
                page.wait_for_url(
                    lambda url: "school-picker" not in url,
                    timeout=12000
                )
            except Exception:
                screenshot_path = f"vali_picker_stuck_{district_id[:8]}.png"
                page.screenshot(path=screenshot_path)
                raise Exception(
                    f"URL did not change away from school-picker after clicking suggestion. "
                    f"Screenshot: {screenshot_path}"
                )

            page.wait_for_load_state("domcontentloaded", timeout=8000)
            print(f"   [SSO] Post-picker URL: {page.url}")

        # Step 2b: Auth method picker appears again after district selection.
        # Clever shows Badge | Password a second time at the district level.
        print(f"   [SSO] Step 2b: Checking for second auth method picker...")
        _click_password_card(page)

        # Step 3: Username form — enter username and click Next.
        print(f"   [SSO] Step 3: Looking for username input...")
        username_selectors = [
            'input[name="username"]',
            'input[id="username"]',
            'input[type="text"]',
            'input[type="email"]',
            'input[autocomplete="username"]',
        ]
        username_selector = None
        for sel in username_selectors:
            try:
                page.wait_for_selector(sel, timeout=6000)
                username_selector = sel
                break
            except Exception:
                continue

        if not username_selector:
            screenshot_path = f"vali_login_debug_{username[:8]}.png"
            page.screenshot(path=screenshot_path)
            raise Exception(
                f"Username input not found. Tried: {username_selectors}. "
                f"Screenshot saved to {screenshot_path}"
            )

        page.fill(username_selector, username)
        print(f"   [SSO] Username filled. URL before Next: {page.url}")
        print(f"   [SSO] Clicking Next...")

        for sel in ['button:has-text("Next")', 'button[type="submit"]']:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        # Step 4: Password form — appears on a separate page after username.
        print(f"   [SSO] Step 4: Looking for password input...")
        password_selectors = [
            'input[name="password"]',
            'input[id="password"]',
            'input[type="password"]',
        ]
        password_selector = None
        for sel in password_selectors:
            try:
                page.wait_for_selector(sel, timeout=8000)
                password_selector = sel
                break
            except Exception:
                continue

        if not password_selector:
            screenshot_path = f"vali_password_debug_{username[:8]}.png"
            page.screenshot(path=screenshot_path)
            raise Exception(
                f"Password input not found after submitting username. "
                f"Screenshot saved to {screenshot_path}"
            )

        page.fill(password_selector, password)
        print(f"   [SSO] Password filled. Clicking Next...")

        for sel in ['button:has-text("Next")', 'button[type="submit"]']:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        # Step 5: Wait for redirect back to the partner app.
        print(f"   [SSO] Step 5: Waiting for redirect to partner app...")
        page.wait_for_url(lambda url: "clever.com" not in url, timeout=15000)
        print(f"   [SSO] Redirected to: {page.url}")
        return True

    except Exception as e:
        print(f"   [!] Clever login failed: {e}")
        return False


def _detect_sso_success(page, user):
    """
    Layered success detection after an SSO login attempt.

    Layer 1 — Name match: look for the user's name on the page.
    Layer 2 — No error keywords: check the page doesn't show an error.
    Layer 3 — URL signal: verify we've left clever.com.

    Returns a (success: bool, confidence: str, detail: str) tuple.
    confidence is "high", "medium", or "low".
    """
    page_text = page.inner_text("body").lower()
    name_lower = user["name"].lower()

    # Layer 1: name present on page
    if name_lower in page_text:
        return True, "high", f"User's name '{user['name']}' found on page after login."

    # Layer 2: check for error keywords
    error_keywords = ["error", "invalid", "unauthorized", "not found",
                      "something went wrong", "access denied", "forbidden"]
    found_errors = [kw for kw in error_keywords if kw in page_text]
    if found_errors:
        return False, "high", (
            f"Error keywords found on page after login: {found_errors}. "
            f"App may not have recognised the user."
        )

    # Layer 3: we've left clever.com — likely succeeded but name wasn't visible
    current_url = page.url
    if "clever.com" not in current_url:
        return True, "medium", (
            f"Redirected to '{current_url}' — login appears successful, "
            f"but user's name was not found on the page. "
            f"This may be normal for apps that don't display names (e.g. games)."
        )

    return False, "low", "Still on clever.com after login attempt — redirect did not complete."


# ---------------------------------------------------------------------------
# OAUTH SECURITY TESTS
# ---------------------------------------------------------------------------

def test_missing_state(config):
    """Verifies the app rejects OAuth callbacks with no state parameter."""
    if not config.get("use_state"):
        return _result(
            "OAuth: Missing state rejected",
            "SKIPPED",
            "App does not use the state parameter — test skipped.",
            "OAuth Security"
        )
    try:
        response = _get_with_backoff(
            f"{config['callback_url']}?code=fake_code_123",
            allow_redirects=False, timeout=10
        )
        if response.status_code == 429:
            return _result("OAuth: Missing state rejected", "NEEDS_WORK",
                "Rate limited after all retries. Try again in a few minutes.",
                "OAuth Security")
        elif response.status_code in [400, 401, 403]:
            return _result("OAuth: Missing state rejected", "PASS",
                "App correctly rejected auth request without state.",
                "OAuth Security")
        else:
            return _result("OAuth: Missing state rejected", "FAIL",
                f"Expected 400/401/403, got {response.status_code}.",
                "OAuth Security")
    except requests.exceptions.Timeout:
        return _result("OAuth: Missing state rejected", "FAIL",
            "Server did not respond within 10 seconds.", "OAuth Security")
    except requests.exceptions.RequestException:
        return _result("OAuth: Missing state rejected", "FAIL",
            "Server crashed or unreachable.", "OAuth Security")


def test_forged_state(config):
    """Verifies the app rejects a state value it never issued."""
    if not config.get("use_state"):
        return _result(
            "OAuth: Forged state rejected",
            "SKIPPED",
            "App does not use the state parameter — test skipped.",
            "OAuth Security"
        )
    try:
        url = (f"{config['callback_url']}?code=fake_code_123"
               f"&state=VALI_CSRF_PROBE_NOT_A_REAL_SESSION")
        response = _get_with_backoff(url, allow_redirects=False, timeout=10)
        if response.status_code == 429:
            return _result("OAuth: Forged state rejected", "NEEDS_WORK",
                "Rate limited after all retries. Try again in a few minutes.",
                "OAuth Security")
        elif response.status_code in [400, 401, 403]:
            return _result("OAuth: Forged state rejected", "PASS",
                "App correctly rejected a state value it never issued.",
                "OAuth Security")
        else:
            return _result("OAuth: Forged state rejected", "FAIL",
                f"App accepted a forged state value (status {response.status_code}). "
                f"State must be validated against active sessions.",
                "OAuth Security")
    except requests.exceptions.Timeout:
        return _result("OAuth: Forged state rejected", "FAIL",
            "Server did not respond within 10 seconds.", "OAuth Security")
    except requests.exceptions.RequestException:
        return _result("OAuth: Forged state rejected", "FAIL",
            "Server crashed or unreachable.", "OAuth Security")


def test_invalid_code(config):
    """Verifies the app handles an invalid authorization code without crashing."""
    try:
        url = f"{config['callback_url']}?code=invalid_forged_code_999"
        if config.get("use_state"):
            url += "&state=VALI_CSRF_PROBE_NOT_A_REAL_SESSION"
        response = _get_with_backoff(url, allow_redirects=False, timeout=10)
        if response.status_code == 429:
            return _result("OAuth: Graceful code rejection", "NEEDS_WORK",
                "Rate limited after all retries. Try again in a few minutes.",
                "OAuth Security")
        elif response.status_code in [302, 303, 400, 401]:
            return _result("OAuth: Graceful code rejection", "PASS",
                "App safely handled invalid authorization code.",
                "OAuth Security")
        elif response.status_code == 500:
            return _result("OAuth: Graceful code rejection", "FAIL",
                "App crashed (500) when Clever rejected the code. "
                "Add error handling around the token exchange step.",
                "OAuth Security")
        else:
            return _result("OAuth: Graceful code rejection", "NEEDS_WORK",
                f"Unexpected status {response.status_code}.",
                "OAuth Security")
    except requests.exceptions.Timeout:
        return _result("OAuth: Graceful code rejection", "FAIL",
            "Server did not respond within 10 seconds.", "OAuth Security")
    except requests.exceptions.RequestException:
        return _result("OAuth: Graceful code rejection", "FAIL",
            "Server crashed.", "OAuth Security")


# ---------------------------------------------------------------------------
# SSO BEHAVIOR TESTS (Playwright)
# ---------------------------------------------------------------------------

def test_sso_role_coverage(config):
    """
    Logs into the partner's app as a student, teacher, and admin via
    Clever SSO. Verifies each role is recognised after login.

    This catches the most common data ingestion failure modes without
    requiring a diagnostic file — if Teacher 50 can't log in, the app
    isn't provisioning teachers regardless of what their database says.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _result(
            "SSO: Role coverage",
            "SKIPPED",
            "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            "SSO Behavior"
        )

    login_url = config.get("login_url", "")
    if not login_url:
        return _result(
            "SSO: Role coverage",
            "SKIPPED",
            "No login_url provided in config. Add the partner's login page URL to run SSO tests.",
            "SSO Behavior"
        )

    # Test one user per role — we don't need to test every sandbox user,
    # just enough to verify each role type is handled.
    test_users = [u for u in SANDBOX_USERS if u["username"] and u["password"]]
    if not test_users:
        return _result(
            "SSO: Role coverage",
            "SKIPPED",
            "No sandbox user credentials configured in SANDBOX_USERS. "
            "Fill in username and password for each user to enable SSO tests.",
            "SSO Behavior"
        )

    role_results = {}   # role -> (success, confidence, detail)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
            ]
        )
        # Use a real Chrome user agent so Clever's servers don't
        # fingerprint the request as coming from a headless bot.
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

        for user in test_users:
            print(f"   [SSO] Testing {user['role']} login: {user['name']}...")
            context = browser.new_context(user_agent=ua)
            page = context.new_page()

            try:
                # Navigate to the partner's login page and trigger Clever SSO.
                page.goto(login_url, timeout=15000)

                # Click the "Log in with Clever" button.
                # We try common selectors — partners implement this differently.
                clever_btn_selectors = [
                    'a[href*="clever.com"]',
                    'a:has-text("Clever")',
                    'button:has-text("Clever")',
                    'a:has-text("Log in with Clever")',
                    '[class*="clever"]',
                ]
                clicked = False
                for selector in clever_btn_selectors:
                    try:
                        page.click(selector, timeout=3000)
                        clicked = True
                        break
                    except Exception:
                        continue

                if not clicked:
                    role_results[user["role"]] = (
                        False, "high",
                        f"Could not find a 'Log in with Clever' button on {login_url}. "
                        f"Tried selectors: {clever_btn_selectors}"
                    )
                    context.close()
                    continue

                # Wait for Clever's login page to fully load after the button click.
                # Without this, _clever_login starts looking for the username input
                # before the page has finished navigating to clever.com.
                try:
                    page.wait_for_url(lambda url: "clever.com" in url, timeout=10000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass  # If this times out, _clever_login will handle it

                # Complete the Clever login flow.
                login_ok = _clever_login(page, user["username"], user["password"], user.get("district_id", ""))
                if not login_ok:
                    role_results[user["role"]] = (
                        False, "high",
                        f"Clever login flow did not complete for {user['name']} ({user['role']})."
                    )
                    context.close()
                    continue

                # Detect whether the app recognised the user.
                success, confidence, detail = _detect_sso_success(page, user)
                role_results[user["role"]] = (success, confidence, detail)

            except Exception as e:
                role_results[user["role"]] = (
                    False, "high",
                    f"Unexpected error during {user['role']} login test: {e}"
                )
            finally:
                context.close()

        browser.close()

    # Build the combined result from all role outcomes.
    failed_roles  = [r for r, (ok, _, _) in role_results.items() if not ok]
    medium_roles  = [r for r, (ok, conf, _) in role_results.items() if ok and conf == "medium"]
    passed_roles  = [r for r, (ok, conf, _) in role_results.items() if ok and conf == "high"]

    detail_lines = []
    for role, (ok, conf, detail) in sorted(role_results.items()):
        icon = "✓" if ok else "✗"
        detail_lines.append(f"  {icon} [{role.upper()}] {detail}")

    if failed_roles:
        return _result(
            "SSO: Role coverage",
            "FAIL",
            f"Login failed for role(s): {', '.join(failed_roles)}\n\n"
            + "\n".join(detail_lines)
            + "\n\nThis typically means the app is not provisioning these role types. "
            + "Check your ingestion logic and token scopes.",
            "SSO Behavior"
        )
    elif medium_roles:
        return _result(
            "SSO: Role coverage",
            "NEEDS_WORK",
            f"All roles redirected successfully, but user name was not visible on the page "
            f"for: {', '.join(medium_roles)}. This may be normal for certain app types.\n\n"
            + "\n".join(detail_lines),
            "SSO Behavior"
        )
    else:
        return _result(
            "SSO: Role coverage",
            "PASS",
            f"All tested roles logged in successfully: {', '.join(sorted(passed_roles))}\n\n"
            + "\n".join(detail_lines),
            "SSO Behavior"
        )


def test_sso_missing_fields(config):
    """
    Logs in as a sandbox user with a sparse profile (missing optional
    fields like email, last name, etc.) and checks whether the app
    handles the missing data gracefully rather than crashing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _result(
            "SSO: Missing field handling",
            "SKIPPED",
            "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            "SSO Behavior"
        )

    login_url = config.get("login_url", "")
    if not login_url:
        return _result("SSO: Missing field handling", "SKIPPED",
            "No login_url provided in config.", "SSO Behavior")

    if not SPARSE_USER.get("username") or not SPARSE_USER.get("password"):
        return _result("SSO: Missing field handling", "SKIPPED",
            "No sparse user credentials configured in SPARSE_USER. "
            "Fill in the credentials to enable this test.",
            "SSO Behavior")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        context = browser.new_context(user_agent=ua)
        page = context.new_page()

        try:
            page.goto(login_url, timeout=15000)

            clever_btn_selectors = [
                'a[href*="clever.com"]',
                'a:has-text("Clever")',
                'button:has-text("Clever")',
                'a:has-text("Log in with Clever")',
                '[class*="clever"]',
            ]
            clicked = False
            for selector in clever_btn_selectors:
                try:
                    page.click(selector, timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                return _result("SSO: Missing field handling", "SKIPPED",
                    f"Could not find a 'Log in with Clever' button on {login_url}.",
                    "SSO Behavior")

            login_ok = _clever_login(
                page, SPARSE_USER["username"], SPARSE_USER["password"], SPARSE_USER.get("district_id", "")
            )
            if not login_ok:
                return _result("SSO: Missing field handling", "FAIL",
                    "Clever login did not complete for sparse profile user. "
                    "Check credentials in SPARSE_USER config.",
                    "SSO Behavior")

            # Check for crash indicators — a 500 or error page after login
            # means the app doesn't handle missing fields gracefully.
            page_text = page.inner_text("body").lower()
            crash_keywords = ["500", "internal server error", "something went wrong",
                              "unhandled exception", "null pointer", "undefined"]
            found_crashes = [kw for kw in crash_keywords if kw in page_text]

            if found_crashes:
                return _result(
                    "SSO: Missing field handling",
                    "FAIL",
                    f"App appears to have crashed after logging in with a sparse profile user. "
                    f"Keywords found: {found_crashes}. "
                    f"Ensure all non-required Clever fields are treated as optional.",
                    "SSO Behavior"
                )

            success, confidence, detail = _detect_sso_success(page, SPARSE_USER)
            if success:
                return _result(
                    "SSO: Missing field handling",
                    "PASS",
                    f"App handled sparse profile user gracefully. {detail}",
                    "SSO Behavior"
                )
            else:
                return _result(
                    "SSO: Missing field handling",
                    "FAIL",
                    f"App did not recognise sparse profile user after login. {detail} "
                    f"Check that missing optional fields don't block user provisioning.",
                    "SSO Behavior"
                )

        except Exception as e:
            return _result("SSO: Missing field handling", "FAIL",
                f"Unexpected error: {e}", "SSO Behavior")
        finally:
            context.close()
            browser.close()


def test_sso_session_invalidation(config):
    """
    Verifies that a new Clever login invalidates any existing session.

    Logs in as User A, captures their session, then logs in as User B
    in a separate browser context. Goes back to User A's context and
    checks whether their session was invalidated — the app should not
    still recognise User A after User B has logged in.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _result(
            "SSO: Session invalidation",
            "SKIPPED",
            "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            "SSO Behavior"
        )

    login_url = config.get("login_url", "")
    if not login_url:
        return _result("SSO: Session invalidation", "SKIPPED",
            "No login_url provided in config.", "SSO Behavior")

    # Need at least two users with credentials for this test.
    # We use clever_id (Clever UUID) as the stable identifier here —
    # not sis_id — because clever_id is what the app should be using
    # as its primary key.
    credentialled = [u for u in SANDBOX_USERS if u["username"] and u["password"]]
    if len(credentialled) < 2:
        return _result("SSO: Session invalidation", "SKIPPED",
            "At least two sandbox users with credentials are required. "
            "Fill in username and password for two or more users in SANDBOX_USERS.",
            "SSO Behavior")

    user_a = credentialled[0]
    user_b = credentialled[1]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

        # Step 1: Log in as User A and capture a URL that requires auth.
        print(f"   [SSO] Session test: logging in as User A ({user_a['name']})...")
        context_a = browser.new_context(user_agent=ua)
        page_a = context_a.new_page()

        try:
            page_a.goto(login_url, timeout=15000)
            clever_btns = [
                'a[href*="clever.com"]', 'a:has-text("Clever")',
                'button:has-text("Clever")', 'a:has-text("Log in with Clever")',
                '[class*="clever"]',
            ]
            for sel in clever_btns:
                try:
                    page_a.click(sel, timeout=3000)
                    break
                except Exception:
                    continue


                # Wait for Clever's login page to load before attempting login.
                try:
                    page_a.wait_for_url(lambda url: "clever.com" in url, timeout=10000)
                    page_a.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
            login_ok = _clever_login(page_a, user_a["username"], user_a["password"], user_a.get("district_id", ""))
            if not login_ok:
                return _result("SSO: Session invalidation", "FAIL",
                    f"Could not complete login for User A ({user_a['name']}). "
                    "Check credentials.", "SSO Behavior")

            # Capture the authenticated URL to revisit later.
            authenticated_url = page_a.url
            print(f"   [SSO] User A logged in. Authenticated URL: {authenticated_url}")

        except Exception as e:
            context_a.close()
            browser.close()
            return _result("SSO: Session invalidation", "FAIL",
                f"Error during User A login: {e}", "SSO Behavior")

        # Step 2: Log in as User B in a separate context (simulates a new device).
        print(f"   [SSO] Session test: logging in as User B ({user_b['name']})...")
        context_b = browser.new_context(user_agent=ua)
        page_b = context_b.new_page()

        try:
            page_b.goto(login_url, timeout=15000)
            for sel in clever_btns:
                try:
                    page_b.click(sel, timeout=3000)
                    break
                except Exception:
                    continue


                # Wait for Clever's login page to load before attempting login.
                try:
                    page_b.wait_for_url(lambda url: "clever.com" in url, timeout=10000)
                    page_b.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
            login_ok = _clever_login(page_b, user_b["username"], user_b["password"], user_b.get("district_id", ""))
            if not login_ok:
                return _result("SSO: Session invalidation", "FAIL",
                    f"Could not complete login for User B ({user_b['name']}). "
                    "Check credentials.", "SSO Behavior")

            print(f"   [SSO] User B logged in. Now checking User A's session...")

        except Exception as e:
            context_b.close()
            context_a.close()
            browser.close()
            return _result("SSO: Session invalidation", "FAIL",
                f"Error during User B login: {e}", "SSO Behavior")
        finally:
            context_b.close()

        # Step 3: Go back to User A's context and check if their session is still valid.
        # A correctly implemented app should have invalidated User A's session
        # when User B logged in on the same device/app instance.
        try:
            page_a.goto(authenticated_url, timeout=15000)
            page_a.wait_for_load_state("networkidle", timeout=10000)
            page_text = page_a.inner_text("body").lower()
            user_a_name = user_a["name"].lower()

            # If User A's name is still on the page, their session wasn't invalidated.
            if user_a_name in page_text:
                return _result(
                    "SSO: Session invalidation",
                    "FAIL",
                    f"User A ({user_a['name']}) session was still active after User B logged in. "
                    f"Each new Clever login must invalidate existing sessions. "
                    f"See: https://dev.clever.com/docs/il-security#shared-devices-session-re-authentication-and-session-invalidation",
                    "SSO Behavior"
                )

            # If we're redirected to a login page, the session was correctly invalidated.
            redirect_indicators = ["login", "sign in", "log in", "clever.com"]
            if any(ind in page_a.url.lower() or ind in page_text for ind in redirect_indicators):
                return _result(
                    "SSO: Session invalidation",
                    "PASS",
                    f"User A's session was correctly invalidated after User B logged in. "
                    f"App redirected to login when User A's session was revisited.",
                    "SSO Behavior"
                )

            # Ambiguous — session may or may not be valid, name just not visible.
            return _result(
                "SSO: Session invalidation",
                "NEEDS_WORK",
                f"Could not definitively confirm session invalidation. "
                f"User A's name was not found, but the app didn't clearly redirect to login either. "
                f"Manual verification recommended.",
                "SSO Behavior"
            )

        except Exception as e:
            return _result("SSO: Session invalidation", "FAIL",
                f"Error checking User A's session after User B login: {e}",
                "SSO Behavior")
        finally:
            context_a.close()
            browser.close()


# ---------------------------------------------------------------------------
# TEST REGISTRY
# ---------------------------------------------------------------------------
# Each entry defines one test. To add a new test:
#   1. Write a function above that returns _result(...)
#   2. Add one entry here — that's it, no other changes needed.
#
# Fields:
#   fn              — the test function to call
#   category        — groups tests in the dashboard (OAuth Security, SSO Behavior, etc.)
#   requires_browser — True if the test needs Playwright; used by the runner
#                      to skip browser tests when Playwright isn't installed
#   enabled         — set False to temporarily disable without deleting

TEST_REGISTRY = [
    # OAuth Security
    {
        "fn":               test_missing_state,
        "category":         "OAuth Security",
        "requires_browser": False,
        "enabled":          True,
    },
    {
        "fn":               test_forged_state,
        "category":         "OAuth Security",
        "requires_browser": False,
        "enabled":          True,
    },
    {
        "fn":               test_invalid_code,
        "category":         "OAuth Security",
        "requires_browser": False,
        "enabled":          True,
    },
    # SSO Behavior
    {
        "fn":               test_sso_role_coverage,
        "category":         "SSO Behavior",
        "requires_browser": True,
        "enabled":          True,
    },
    {
        "fn":               test_sso_missing_fields,
        "category":         "SSO Behavior",
        "requires_browser": True,
        "enabled":          True,
    },
    {
        "fn":               test_sso_session_invalidation,
        "category":         "SSO Behavior",
        "requires_browser": True,
        "enabled":          True,
    },
]


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

def run_all_tests(config):
    """
    Iterates the TEST_REGISTRY and runs every enabled test.
    Returns a flat list of result dicts and an overall pass/fail bool.

    The dashboard calls this instead of calling individual test functions.
    Adding a new test to the registry is all that's needed to include it
    in every future run.
    """
    results = []
    playwright_available = _check_playwright()

    for entry in TEST_REGISTRY:
        if not entry.get("enabled", True):
            continue

        # Skip browser tests gracefully if Playwright isn't installed.
        if entry["requires_browser"] and not playwright_available:
            results.append(_result(
                entry["fn"].__name__.replace("test_", "").replace("_", " ").title(),
                "SKIPPED",
                "Playwright not installed — browser tests skipped. "
                "Run: pip install playwright && playwright install chromium",
                entry["category"]
            ))
            continue

        print(f"[TEST] {entry['fn'].__name__}...")
        try:
            result = entry["fn"](config)
            results.append(result)
        except Exception as e:
            # Catch unexpected errors so one broken test doesn't abort the run.
            results.append(_result(
                entry["fn"].__name__,
                "FAIL",
                f"Test raised an unexpected error: {e}",
                entry["category"]
            ))

    failing = {"FAIL", "NEEDS_WORK"}
    overall_pass = not any(r["status"] in failing for r in results)
    return results, overall_pass


def _check_playwright():
    """Returns True if Playwright is installed and usable."""
    try:
        from playwright.sync_api import sync_playwright  # noqa
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# DATA LOADING (kept for backward compatibility / CLI mode)
# ---------------------------------------------------------------------------

def is_user_active(user):
    """Flexibly determines if a user is active across multiple schema conventions."""
    if "status" in user and user["status"] != "":
        return str(user["status"]).strip().lower() == "active"
    if "is_active" in user:
        return bool(user["is_active"])
    if "is_archived" in user:
        return not bool(user["is_archived"])
    if "deleted_at" in user:
        return user["deleted_at"] is None or str(user["deleted_at"]).strip() == ""
    return True


def load_diagnostic_data(filepath):
    """Loads and validates a diagnostic JSON file (legacy / optional)."""
    if not os.path.exists(filepath):
        return None
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        print(f"[!] File too large ({size_mb:.1f} MB). Max is {MAX_FILE_SIZE_MB} MB.")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"[!] Invalid JSON in '{filepath}'.")
            return None
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        print("[!] JSON must be { \"users\": [...] }")
        return None
    data["users"] = [u for u in data["users"] if isinstance(u, dict)]
    return data


# ---------------------------------------------------------------------------
# CLI ENTRY POINT (optional — dashboard is the primary interface now)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("="*50)
    print("⚡ Vali — Clever Certification Validator")
    print("="*50)

    config = {
        "use_state":    True,
        "callback_url": input("Callback URL [http://localhost:8080/auth/clever/callback]: ").strip()
                        or "http://localhost:8080/auth/clever/callback",
        "login_url":    input("App login URL (for SSO tests, leave blank to skip): ").strip(),
        "data_file":    "diagnostic.json",
    }

    results, overall_pass = run_all_tests(config)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename  = f"certification_report_{timestamp}.json"

    report = {
        "validator_version": "v3.0-Internal",
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "overall_status":    "PASS" if overall_pass else "NEEDS_WORK",
        "results":           results,
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nVALIDATION COMPLETE: {report['overall_status']}")
    print(f"Report saved to -> {filename}")