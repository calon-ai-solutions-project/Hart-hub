"""
Motorway Pro (pro.motorway.co.uk) login automation (Playwright, visible Chrome window).

- Opens the Motorway dealer sign-in page.
- Waits for the page to load (and for any CAPTCHA - solve it yourself in the window).
- Waits 30 seconds, then types email and password slowly and clicks Sign in.
- Saves the logged-in session to motorway_session.json for motorway_scraper.py.

Usage:
    python scrapers/motorway_login.py
    python scrapers/motorway_login.py --dry-run   # stop before typing (to test the flow)
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

SIGN_IN_URL = os.getenv("MOTORWAY_LOGIN_URL") or "https://pro.motorway.co.uk/signin"
EMAIL = os.getenv("MOTORWAY_EMAIL")
PASSWORD = os.getenv("MOTORWAY_PASSWORD")
WAIT_BEFORE_TYPING = int(os.getenv("MOTORWAY_WAIT_SECONDS", "30"))
SESSION_FILE = SESSIONS / "motorway_session.json"
DRY_RUN = "--dry-run" in sys.argv

EMAIL_FIELD = "#username"
PASSWORD_FIELD = "#password"
REMEMBER_ME = "#remember"  # "Keep me signed in on this device."
SUBMIT = "form:has(#username) button[type='submit']"

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


def on_sign_in_page(url):
    return "/signin" in url


def wait_for_login_form(page, timeout=300):
    print("Waiting for page and security checks to finish...")
    deadline = time.time() + timeout
    warned = False
    stable_since = None
    while time.time() < deadline:
        # With a valid saved session /signin sends us on to the vehicle list, so only
        # count as logged in if we stay off the sign-in page for 10s
        if "pro.motorway.co.uk" in page.url and not on_sign_in_page(page.url):
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 10:
                return "logged_in"
        else:
            stable_since = None
        if not captcha_present(page) and page.locator(EMAIL_FIELD).is_visible():
            return "form"
        if captcha_present(page) and not warned:
            print(">> CAPTCHA detected - please solve it in the browser window. Waiting...")
            warned = True
        time.sleep(2)
    raise TimeoutError("Login form did not appear in time.")


def login(page):
    print(f"Opening {SIGN_IN_URL} ...")
    page.goto(SIGN_IN_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("load")
    human_pause(2, 4)

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
    try:
        if remember.count() > 0 and not remember.is_checked():
            remember.check(timeout=5000)
            human_pause()
    except Exception:
        pass  # styled checkbox not clickable - not needed to log in

    submit = page.locator(SUBMIT).first
    try:
        submit.hover(timeout=5000)
        human_pause(0.4, 1.0)
        submit.click(timeout=10000)
    except PlaywrightTimeout:
        print("Sign in button not clickable - pressing Enter instead.")
        page.locator(PASSWORD_FIELD).press("Enter")
    print("Clicked Sign in, waiting...")

    try:
        page.wait_for_url(lambda url: not on_sign_in_page(url), timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError(
            "Still on the sign-in page. Check the browser for an error "
            "(wrong password, CAPTCHA, or verification needed)."
        )
    page.wait_for_load_state("load")
    human_pause(3, 5)
    print(f"Logged in. Current page: {page.url}")
    return True


def main():
    if not EMAIL or not PASSWORD:
        raise SystemExit("Set MOTORWAY_EMAIL and MOTORWAY_PASSWORD in your .env file.")

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
