"""
Carwow dealer login automation (Playwright, visible Chrome window).

- Reads credentials from environment variables / .env (never hard-coded).
- Waits for the page to fully load and for any security check / CAPTCHA
  to clear. If a CAPTCHA needs solving, it pauses so YOU can solve it in
  the browser window, then carries on.
- Types email and password slowly, character by character.
- Saves the logged-in session to carwow_session.json so later runs can
  skip the login entirely.

Usage:
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env      # then fill in your details
    python scrapers/carwow_login.py
"""

import os
import random
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from paths import ROOT, SESSIONS, rel

load_dotenv(ROOT / ".env")

LOGIN_URL = os.getenv("CARWOW_LOGIN_URL", "https://www.carwow.co.uk/partners/partner-with-carwow")
SIGN_IN_URL = "https://dealers.carwow.co.uk/dealers/sign_in"
DRY_RUN = "--dry-run" in sys.argv
WAIT_BEFORE_TYPING = int(os.getenv("CARWOW_WAIT_SECONDS", "30"))
EMAIL = os.getenv("CARWOW_EMAIL")
PASSWORD = os.getenv("CARWOW_PASSWORD")
SESSION_FILE = SESSIONS / "carwow_session.json"

CAPTCHA_SELECTORS = [
    "iframe[src*='captcha']",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[title*='challenge' i]",
    "#cf-challenge-running",
    ".g-recaptcha",
    ".h-captcha",
]


def human_pause(low=0.6, high=1.6):
    time.sleep(random.uniform(low, high))


def slow_type(page, selector, text):
    """Click a field and type into it one character at a time."""
    field = page.locator(selector)
    field.click()
    human_pause(0.3, 0.8)
    for ch in text:
        field.press_sequentially(ch, delay=random.randint(80, 220))
    human_pause()


def captcha_present(page):
    return any(page.locator(sel).count() > 0 for sel in CAPTCHA_SELECTORS)


def wait_for_security(page, timeout=300):
    """Wait until no CAPTCHA / security check is on screen and the login form is usable.

    Automatic checks (e.g. Cloudflare's "checking your browser") usually clear by
    themselves. If an interactive CAPTCHA is shown, solve it yourself in the window.
    """
    print("Waiting for page and security checks to finish...")
    page.wait_for_load_state("networkidle")
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        if not captcha_present(page) and page.locator("#username").is_visible():
            print("Security check passed, login form ready.")
            return True
        if captcha_present(page) and not warned:
            print(">> CAPTCHA detected - please solve it in the browser window. Waiting...")
            warned = True
        time.sleep(2)
    raise TimeoutError("Security check / CAPTCHA did not clear in time.")


def click_login_button(page):
    """Open the Carwow partner page and click its "Log In" link."""
    print(f"Opening {LOGIN_URL} ...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    human_pause(2, 4)

    # Close the cookie banner if it covers the page (rejects optional cookies)
    for label in ("Reject all", "Reject", "Necessary only"):
        btn = page.get_by_role("button", name=label)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            human_pause()
            break

    # The page has several "Log In" links (some hidden in the mobile menu) - use a visible one
    login_link = page.locator("a[href*='/dealers/sign_in']:visible").first
    try:
        login_link.wait_for(state="visible", timeout=30000)
    except PlaywrightTimeout:
        print("No visible Log In link found - going to the sign-in page directly.")
        page.goto(SIGN_IN_URL, wait_until="domcontentloaded")
        return
    login_link.scroll_into_view_if_needed()
    login_link.hover()
    human_pause(0.5, 1.2)
    print("Clicking Log In...")
    login_link.click()


def find_sign_in_page(context, timeout=90):
    """After clicking Log In, wait until a tab shows the email field or the dealer dashboard.

    Returns (page, "form") or (page, "logged_in").
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pg in reversed(context.pages):  # newest tab first (Log In may open a new tab)
            try:
                if pg.locator("#username").is_visible():
                    return pg, "form"
                url = pg.url
                if "dealers.carwow.co.uk" in url and not any(
                    part in url for part in ("/sign_in", "/login")
                ):
                    return pg, "logged_in"
            except Exception:
                pass  # page navigating - try again
        time.sleep(1)
    raise RuntimeError(
        "Clicked Log In but the sign-in form never appeared. Last URLs: "
        + ", ".join(pg.url for pg in context.pages)
    )


def login(context, page):
    click_login_button(page)

    print("Waiting for the sign-in page to load...")
    page, state = find_sign_in_page(context)
    if state == "logged_in":
        print(f"Already logged in (saved session): {page.url}")
        return page

    page.bring_to_front()
    page.wait_for_load_state("load")
    wait_for_security(page)
    print(f"Sign-in page loaded: {page.url.split('?')[0]}")

    print(f"Waiting {WAIT_BEFORE_TYPING}s before typing...")
    time.sleep(WAIT_BEFORE_TYPING)

    if DRY_RUN:
        print("DRY RUN: stopping before typing email/password.")
        return page

    print("Typing email...")
    slow_type(page, "#username", EMAIL)

    # Some Auth0 flows show the password on a second step
    if not page.locator("#password").is_visible():
        page.locator("button[name='action'][type='submit']").click()
        page.locator("#password").wait_for(state="visible", timeout=30000)
        human_pause()

    print("Typing password...")
    slow_type(page, "#password", PASSWORD)

    human_pause(1, 2)
    submit = page.locator("button[name='action'][type='submit']")
    submit.hover()
    human_pause(0.4, 1.0)
    submit.click()
    print("Clicked Continue, waiting for login...")

    # A CAPTCHA or 2FA step can appear after submit - give time to finish it in the window
    try:
        page.wait_for_url(lambda url: "auth.carwow.co.uk" not in url, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError(
            "Still on the login page. Check the browser for an error "
            "(wrong password, CAPTCHA, or 2FA code needed)."
        )
    page.wait_for_load_state("load")
    print(f"Logged in. Current page: {page.url}")
    return page


def main():
    if not EMAIL or not PASSWORD:
        raise SystemExit("Set CARWOW_EMAIL and CARWOW_PASSWORD in your .env file.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(
            storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
            viewport={"width": 1366, "height": 850},
            locale="en-GB",
        )
        page = context.new_page()

        page = login(context, page)
        if not DRY_RUN:
            context.storage_state(path=str(SESSION_FILE))
            print(f"Session saved to {rel(SESSION_FILE)}")

        browser.close()  # the window is only needed for logging in
        print("Browser window closed.")


if __name__ == "__main__":
    main()
