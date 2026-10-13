# Hart Hub

Dealer platform for The Hart Group Automotive Ltd. One repository:

```
backend/        Django project: listing database, platform sync rules, chatbot and quotes API (deployed on Railway)
web/            React + Vite frontend: the staff stock chatbot
sync-runner/    Opens the allowlisted listings and posts them to the backend
                (runs on the dedicated machine with the logged-in sessions, not on Railway)
docs/           Workflow overview and master workflow
CLAUDE.md       Project rules and conventions, loaded by Claude Code
internal/       Calon-only material: git-ignored, never committed or handed over
```

- [backend/README.md](backend/README.md): structure, the sync rules, the API, local setup, Railway.
- [web/README.md](web/README.md): the React frontend, how to run it, sign-in.
- [sync-runner/README.md](sync-runner/README.md): the runner and the per-platform collectors.
- [docs/master-workflow.md](docs/master-workflow.md): how every workflow behaves.

Never commit `.env` files, platform sessions, scraped exports or anything under `internal/`.
