import { useEffect, useState } from "react";

import logo from "../assets/logo.png";

/** The one-time enquiry form a customer opens from the WhatsApp link. No login: the link is the key. */
export default function PublicFormPage({ token }) {
  const [form, setForm] = useState(null);
  const [problem, setProblem] = useState("");
  const [gearbox, setGearbox] = useState("Auto");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    fetch(`/api/public/forms/${encodeURIComponent(token)}`)
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "This page could not be loaded.");
        setForm(data);
        setDone(data.submitted);
      })
      .catch((error) => setProblem(error.message));
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    const answers = { ...Object.fromEntries(new FormData(event.currentTarget)), gearbox };
    setSending(true);
    setProblem("");
    try {
      const response = await fetch(`/api/public/forms/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Something went wrong. Please try again.");
      setDone(true);
    } catch (error) {
      setProblem(error.message);
    } finally {
      setSending(false);
    }
  }

  const field = (name) => form.fields.find((f) => f.name === name);
  const input = (name) => (
    <label className="field" key={name}>
      {field(name).label}
      <input name={name} placeholder={field(name).placeholder} autoComplete="off" />
    </label>
  );

  return (
    <div className="public">
      <header className="public-top">
        <img src={logo} alt="The Hart Group Automotive" />
      </header>
      <main className="public-main">
        {!form && !problem && <div className="skeleton tall" />}
        {problem && !form && <p className="public-note">{problem}</p>}

        {form && done && (
          <div className="public-note">
            <h1>Thank you ✅</h1>
            <p>We’ve got your details. We’ll message you on WhatsApp shortly with your options and finance quotes.</p>
          </div>
        )}

        {form && !done && (
          <form className="public-card enquiry" onSubmit={submit}>
            <h1>What are you looking for?</h1>
            <p className="public-lead">We’ll send you up to 5 cars with finance quotes on WhatsApp.</p>
            {input("make_model")}
            <div className="two">
              {input("colour")}
              {input("needed_by")}
            </div>
            <div className="field">
              Gearbox
              <div className="seg" role="radiogroup" aria-label="Gearbox">
                {field("gearbox").options.map((option) => (
                  <button
                    type="button"
                    key={option}
                    role="radio"
                    aria-checked={gearbox === option}
                    className={gearbox === option ? "on" : ""}
                    onClick={() => setGearbox(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
            <div className="two">
              {input("monthly_budget")}
              {input("deposit")}
            </div>
            {input("part_exchange")}
            {problem && <div className="login-error">{problem}</div>}
            <button className="public-submit" disabled={sending}>
              {sending ? "Sending…" : "Send my details"}
            </button>
            <p className="public-fine">Secure one-time link · no login · linked to your WhatsApp number</p>
          </form>
        )}
      </main>
    </div>
  );
}
