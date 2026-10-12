"""
Manheim UK login automation (Playwright, visible Chrome window).

- Opens the MyManheim dashboard, which redirects to the login page.
- Waits for the page to load (and for any CAPTCHA - solve it yourself in the window).
- Waits 30 seconds, then types email and password slowly and clicks Login.
- Saves the logged-in session to manheim_session.json for manheim_scraper.py.

Usage:
    python scrapers/manheim_login.py
    python scrapers/manheim_login.py --dry-run   # stop before typing (to test the flow)
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

DASHBOARD_URL = os.getenv("MANHEIM_LOGIN_URL") or "https://www.manheim.co.uk/mymanheim/dashboard"
EMAIL = os.getenv("MANHEIM_EMAIL")
PASSWORD = os.getenv("MANHEIM_PASSWORD")
WAIT_BEFORE_TYPING = int(os.getenv("MANHEIM_WAIT_SECONDS", "30"))
SESSION_FILE = SESSIONS / "manheim_session.json"
DRY_RUN = "--dry-run" in sys.argv

EMAIL_FIELD = "[id='loginForm.Email']"
PASSWORD_FIELD = "[id='loginForm.Password']"
REMEMBER_ME = "[id='loginForm.signed']"

CAPTCHA_SELECTORS = [
    "iframe[src*='captcha']",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[title*='challenge' i]",
    ".g-recaptcha",
    ".h-captcha",
]


def human_pause(low=0.6, high=1.6):
    time.sleep(random.uniform(low, high))


def slow_type(page, selector, text):
    field = page.locator(selector)
    field.hover()
    human_pause(0.3, 0.7)
    field.click()
    human_pause(0.3, 0.8)
    for ch in text:
        field.press_sequentially(ch, delay=random.randint(80, 220))
    human_pause()


def captcha_present(page):
    return any(page.locator(sel).count() > 0 for sel in CAPTCHA_SELECTORS)


def wait_for_login_form(page, timeout=300):
    print("Waiting for page and security checks to finish...")
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        if "/Account/LogIn" not in page.url and "/mymanheim" in page.url:
            return "logged_in"
        if not captcha_present(page) and page.locator(EMAIL_FIELD).is_visible():
            return "form"
        if captcha_present(page) and not warned:
            print(">> CAPTCHA detected - please solve it in the browser window. Waiting...")
            warned = True
        time.sleep(2)
    raise TimeoutError("Login form did not appear in time.")


def login(page):
    print(f"Opening {DASHBOARD_URL} ...")
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("load")
    human_pause(2, 4)

    # Close a cookie banner if it covers the page (rejects optional cookies)
    for label in ("Reject all", "Reject All", "Reject", "Necessary only"):
        btn = page.get_by_role("button", name=label)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            human_pause()
            break

    state = wait_for_login_form(page)
    if state == "logged_in":
        print(f"Already logged in (saved session): {page.url}")
        return True

    print(f"Login page loaded. Waiting {WAIT_BEFORE_TYPING}s before typing...")
    time.sleep(WAIT_BEFORE_TYPING)

    if DRY_RUN:
        print("DRY RUN: stopping before typing email/password.")
        return False

    print("Typing email...")
    slow_type(page, EMAIL_FIELD, EMAIL)
    print("Typing password...")
    slow_type(page, PASSWORD_FIELD, PASSWORD)

    remember = page.locator(REMEMBER_ME)
    if remember.count() > 0 and remember.is_visible() and not remember.is_checked():
        remember.check()
        human_pause()

    submit = page.locator(f"form:has({EMAIL_FIELD}) [type='submit']").first
    submit.hover()
    human_pause(0.4, 1.0)
    submit.click()
    print("Clicked Login, waiting...")

    try:
        page.wait_for_url(lambda url: "/Account/LogIn" not in url, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError(
            "Still on the login page. Check the browser for an error "
            "(wrong password, CAPTCHA, or verification needed)."
        )
    page.wait_for_load_state("load")
    print(f"Logged in. Current page: {page.url}")
    return True


def main():
    if not EMAIL or not PASSWORD:
        raise SystemExit("Set MANHEIM_EMAIL and MANHEIM_PASSWORD in your .env file.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(
            storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
            viewport={"width": 1366, "height": 850},
            locale="en-GB",
        )
        page = context.new_page()

        if login(page):
            context.storage_state(path=str(SESSION_FILE))
            print(f"Session saved to {rel(SESSION_FILE)}")
        browser.close()  # the window is only needed for logging in
        print("Browser window closed.")


if __name__ == "__main__":
    main()
