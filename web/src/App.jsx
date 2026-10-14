import { useEffect, useState } from "react";

import { auth, whenSignedOut } from "./api/client.js";
import ChatPage from "./components/ChatPage.jsx";
import HomePage from "./components/HomePage.jsx";
import LoginPage from "./components/LoginPage.jsx";
import PublicCarPage from "./components/PublicCarPage.jsx";
import PublicFormPage from "./components/PublicFormPage.jsx";
import SimulatorPage from "./components/SimulatorPage.jsx";

const SIGNED_OUT = { user: null, app: null };
// Customer pages opened from WhatsApp. They need no sign-in.
const PUBLIC_CAR = window.location.pathname.match(/^\/c\/([A-Za-z0-9_-]+)\/?$/); // /c/<code>: more photos
const PUBLIC_FORM = window.location.pathname.match(/^\/f\/([A-Za-z0-9_-]+)\/?$/); // /f/<code>: the enquiry form

export default function App() {
  if (PUBLIC_CAR) return <PublicCarPage token={PUBLIC_CAR[1]} />;
  if (PUBLIC_FORM) return <PublicFormPage token={PUBLIC_FORM[1]} />;
  return <StaffApp />;
}

/** #chat and #whatsapp open those sections; anything else is the home dashboard. */
const viewOf = (hash) => ({ "#chat": "chat", "#whatsapp": "whatsapp" })[hash] || "home";

function useView() {
  const [view, setView] = useState(viewOf(window.location.hash));
  useEffect(() => {
    const follow = () => setView(viewOf(window.location.hash));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  return view;
}

function StaffApp() {
  const view = useView();
  const [session, setSession] = useState(null); // null until the hub has said who this is
  const [problem, setProblem] = useState("");
  const [justSignedIn, setJustSignedIn] = useState(false);

  useEffect(() => {
    whenSignedOut(() => setSession(SIGNED_OUT));
    auth
      .me()
      .then(setSession)
      .catch((error) => setProblem(error.message));
  }, []);

  async function signOut() {
    try {
      await auth.logout();
    } finally {
      setSession(SIGNED_OUT);
    }
  }

  if (problem) return <main className="login"><p className="login-lead">{problem}</p></main>;
  if (!session) return null;
  if (!session.user) {
    return (
      <LoginPage
        onSignedIn={(signedIn) => {
          setJustSignedIn(true);
          setSession(signedIn);
        }}
      />
    );
  }
  // a section the role does not include opens the home dashboard instead (the server refuses it anyway)
  const allowed = session.user.sections.includes(view) ? view : "home";
  if (allowed === "home") return <HomePage key={session.user.email} user={session.user} onSignOut={signOut} />;
  if (allowed === "whatsapp") return <SimulatorPage user={session.user} onSignOut={signOut} />;
  return (
    <ChatPage
      key={session.user.email}
      user={session.user}
      app={session.app}
      startFresh={justSignedIn}
      onSignOut={signOut}
    />
  );
}
