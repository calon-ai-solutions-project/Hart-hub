import SideNav from "./SideNav.jsx";

// what each finished section is; a role only sees the ones in its `sections`
const SECTIONS = {
  chat: { href: "#chat", title: "Stock chat", text: "Find the best live cars for a customer and get Codeweavers quotes." },
  whatsapp: { href: "#whatsapp", title: "WhatsApp",
              text: "Customer enquiries: form link, quoted options sent automatically, and hand-over." },
};

/** The dashboard after sign-in. Its reports are still being built, so for now it is a clean welcome page
 *  with the sections this role can open. */
export default function HomePage({ user, onSignOut }) {
  const first = (user.name || user.email.split("@")[0]).split(" ")[0];
  const sections = user.sections.filter((s) => SECTIONS[s]);
  return (
    <div className="crm">
      <SideNav user={user} current="home" onSignOut={onSignOut} />
      <div className="crm-main crm-scroll">
        <main className="home-main dash-clean">
          <p className="eyebrow">Dashboard</p>
          <h1>Welcome, {first.charAt(0).toUpperCase() + first.slice(1)}</h1>

          <div className="dev-card">
            <span className="dev-badge">In development</span>
            <h2>Your dashboard is on its way</h2>
            <p>
              Sales figures, enquiries and team performance will appear here. Until then, everything you need is in
              the sections below.
            </p>
          </div>

          {sections.length > 0 && (
            <div className="sections">
              {sections.map((s) => (
                <a key={s} className="section-row" href={SECTIONS[s].href}>
                  <span>
                    <b>{SECTIONS[s].title}</b>
                    <small>{SECTIONS[s].text}</small>
                  </span>
                  <span className="arrow">→</span>
                </a>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
