import { useEffect, useState } from "react";

import { auth, whenSignedOut } from "./api/client.js";
import ChatPage from "./components/ChatPage.jsx";
import LoginPage from "./components/LoginPage.jsx";

const SIGNED_OUT = { user: null, app: null };

export default function App() {
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
