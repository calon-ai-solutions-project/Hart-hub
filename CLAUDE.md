# Hart Hub

Hart Hub is the dealer platform for The Hart Group Automotive Ltd, built by Calon AI Solutions.
It keeps a daily database of cars from trade platforms, turns every customer enquiry into
approved, finance-quoted option cards sent on WhatsApp, and brings customers back through
social posts and campaigns.

## Read before any task

1. `docs/master-workflow.md`: section 02 (ground rules) and section 03 (architecture), then the
   section for the workflow you are touching (F0, W1 to W6).
2. `internal/developer-spec.md` (git-ignored, Calon only; its stack and repository sections describe
   the earlier TypeScript plan, this file is current): data model (04), statuses (05), events (06), the workflow
   spec for your task (07 to 13), AI rules (14), integrations (15), security (16).
3. `docs/workflow-overview.md`: two-page summary if you only need the idea.

If behaviour changes, update the workflow doc in `docs/` and the developer spec in the same task.

## Non-negotiable rules (code review checks every one)

- **WhatsApp is the source of truth.** Replies always go from the same business number the
  customer contacted.
- **Approval before sending.** Nothing reaches a customer (cards, follow-ups, campaigns, posts)
  without a person approving it, unless an owner-set automation flag is on.
- **Finance only from Codeweavers quotes.** Quotes only, no finance applications. AI never
  calculates or invents finance figures. FCA wording is added by code, not AI.
- **Available-until on every option and post**, from the platform end time. Expired listings are
  excluded from matching, cards and posts. Expired cards cannot be sent.
- **Staff-only fields never in customer payloads:** buy price, prep cost, margin, quote reference,
  listing URL, match score and reason. Customer payloads are built ONLY from `CustomerCardSchema`.
- **WhatsApp policy:** free-form only within 24 hours of the customer's last inbound message;
  otherwise an approved template. People who never messaged us (calls, voice AI, imports,
  campaigns) get email by default, WhatsApp only with recorded consent.
- **Platform sync (contract Schedule 1):** only platforms with `SYNC_ENABLED_<PLATFORM>=true`;
  only allowlisted URLs from Hart's saved-search alerts; once per platform per UK day; stop the
  whole run on any CAPTCHA, verification, unusual-activity notice, access denied, 403 or 429.
  Never bypass, never use stealth or anything that hides automation. Log every URL opened.
- **Consent and STOP:** campaigns only to consented customers; STOP on any channel suppresses
  the customer on every channel at once.
- **No real customer data** in git, fixtures, logs or screenshots. Staging uses fake connectors
  and test numbers only and never messages real customers.
- **Secrets** live only in Railway variables and the vault. Platform and Codeweavers logins are
  never in the database, code, logs, chat or email.
- **Exclusivity:** Hart-specific code, prompts, templates and data are never reused for another
  automotive client.

## Conventions

- Money: integer pence. Times: stored UTC, displayed and scheduled in `Europe/London`. IDs: UUID.
- Phones: E.164.
- Every meaningful change writes an event to the append-only `events` table.
- Every AI call goes through the one metered client in `backend/apps/ai` (logs model, prompt version and
  cost to `ai_usage`). Prompts are versioned files with eval sets.
- Settings and defaults (prep cost, gone-quiet days, reminders and so on) are rows in `settings`,
  never hard-coded.
- Vectors only rank inside the hard-filtered set, so a CLA never matches an SLK.

## Stack

Python 3.12, Django 5.2 + Django REST Framework. Jobs: Celery + Redis (worker and beat in one
service). DB: PostgreSQL 16 + pgvector on Railway EU region.
Storage: S3-compatible bucket. Sync runner: Python (requests + Playwright) on a dedicated Calon
machine (not Railway), using the saved logged-in sessions. Web portal: React + Vite in `web/` (session cookie + CSRF, same origin as the API).
AI: OpenRouter (chat model + embeddings model); image model later.

## Repository layout

```
backend/config                  settings (base, local, test, production), urls, celery
backend/apps/core               base models, events, settings rows, UK time helpers
backend/apps/accounts           staff users and roles
backend/apps/listings           listings, photos, pricing, expiry
backend/apps/sourcing           alerts, sync runs and log, platform definitions, normalisers, sync API
backend/apps/ai                 the one metered AI client and the ai_usage log
backend/apps/matching           requirements, parsing, hard filters, ranking, option cards
backend/apps/chat               staff chatbot: conversations and API (the page is in web/)
backend/apps/quotes             Codeweavers finance quotes (Showroom driven in a headless browser)
web/                            React + Vite frontend (staff chatbot); talks only to the backend API
sync-runner/run_sync.py         the daily sync loop
sync-runner/scrapers            sync guard, hub client, per-platform collectors, page parsers, login scripts
docs/                           workflow documents
internal/                       Calon-only specs (git-ignored)
```

New workflows (matching, quotes, connectors, AI, CRM, campaigns) are added as apps under
`backend/apps/`. In each app, rules live in `services/` and views stay thin.

## Branches and environments

- `main` deploys to production (real connectors, real data).
- `develop` deploys to staging (Thursday client test link, fake or test connectors, anonymised data).
- Feature branches run locally with fake connectors and fixtures.

## Definition of done

- Models, migrations and serializers in place before the views that use them.
- Tests with anonymised fixtures pass.
- Rules above unaffected (or signed off by Alom).
- Works on staging and is described in the Thursday update.
- Workflow and spec docs updated if behaviour changed.

## Do not

- Copy or commit anything from `internal/` into this repo. Internal specs are not handed over
  to the client.
- Put real names, phone numbers, emails or registrations in fixtures, tests or logs.
