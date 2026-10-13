# Hart Hub web

The staff portal's frontend: React + Vite. Today it holds the stock chatbot (enquiry form, the five
best cars, Codeweavers finance quotes and their PDFs). It only talks to the backend's API.

## Layout

```
index.html
vite.config.js          dev server on :5173; /api and /media are passed to the backend
src/main.jsx            entry
src/App.jsx             who is signed in: sign-in screen or the chat
src/api/client.js       every API call (session cookie + CSRF token)
src/hooks/useChat.js    chat state: list, open chat, ticked cars, sending, quotes
src/components/         ChatPage, Sidebar, Message, EnquiryForm, CarCard, QuoteCard, QuoteList,
                        Dock (selection bar, filters, composer), Dialogs, LoginPage, Icon
src/lib/format.js       money, miles, UK dates
src/styles/             app.css (the Hart Hub palette), login.css
```

## Run locally

Start the backend first (`cd backend`, `python manage.py runserver`), then:

```bat
cd web
npm install
npm run dev
```

Open http://localhost:5173 and sign in with a staff account (`python manage.py createsuperuser`).
If the backend is not on `http://127.0.0.1:8000`, copy `.env.example` to `.env` and set
`VITE_BACKEND_URL`.

## Sign-in

The backend keeps the session in an HttpOnly cookie; nothing is stored in the browser by this app.

| Call | Purpose |
| --- | --- |
| `GET /api/auth/me` | Who is signed in (`user` is null when nobody is); sets the CSRF cookie |
| `POST /api/auth/login` | `{"email": "...", "password": "..."}` |
| `POST /api/auth/logout` | End the session |

## Build and deploy

`npm run build` writes static files to `dist/`. They must be served from the **same origin** as the
API, so the session and CSRF cookies work without CORS.

On Railway this is its own service (root directory `web`, config `railway.json`): the `Dockerfile`
builds the app and Caddy serves it, passing `/api` and `/media` to the backend over the private
network (`Caddyfile`). One variable is needed:

```
BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000
```

The backend service needs `PORT=8000`, and this service's public domain in its `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS`.

## Rules that apply here

- A card has a `customer` part and a `staff` part. Anything built for a customer uses `customer` only.
- Finance figures are shown exactly as Codeweavers returned them. Nothing is calculated in the browser.
