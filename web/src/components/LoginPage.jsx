import { useState } from "react";

import { auth } from "../api/client.js";
import logo from "../assets/logo.png";

/** Staff sign-in. The session lives in an HttpOnly cookie set by the hub; nothing is kept in the browser. */
export default function LoginPage({ onSignedIn }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      onSignedIn(await auth.login(form.get("email").trim(), form.get("password")));
    } catch (problem) {
      setError(problem.status === 429 ? "Too many attempts. Wait a minute and try again." : problem.message);
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <img src={logo} alt="The Hart Group Automotive" />
        </div>
        <h1>Sign in</h1>
        <p className="login-lead">Stock assistant for The Hart Group staff.</p>
        <label>
          Email
          <input name="email" type="email" autoComplete="username" required autoFocus />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}
        <button className="btn primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
