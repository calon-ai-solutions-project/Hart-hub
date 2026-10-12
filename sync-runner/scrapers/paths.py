"""Project folders shared by every login script and scraper.

Everything is anchored to the project root, so the scripts work no matter which
folder they are started from.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "sessions"      # saved logins: <site>_session.json
EXPORTS = ROOT / "export_data"    # scraped data: <site>_export/
LOGS = ROOT / "logs"

SESSIONS.mkdir(exist_ok=True)


def rel(path):
    """A path as shown on screen / stored in cars.csv: relative to the project root."""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)
