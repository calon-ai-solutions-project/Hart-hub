import logo from "../assets/logo.png";
import Icon from "./Icon.jsx";

const LINKS = [
  ["home", "#home", "Dashboard", "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"],
  ["chat", "#chat", "Stock chat", "M4 5h16v11H8l-4 4zM8 9h8M8 12h5"],
  ["whatsapp", "#whatsapp", "WhatsApp",
   "M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3zM8.5 9.5c.5 2 2 3.5 4 4l1.2-1.1 2 .9-.6 1.8c-3.6.2-7-3.2-6.8-6.8l1.8-.6.9 2z"],
];

/** The CRM's left menu: the sections this role may open, and who is signed in. */
export default function SideNav({ user, current, onSignOut, counts = {} }) {
  const links = LINKS.filter(([section]) => user.sections.includes(section));
  return (
    <aside className="sidenav">
      <div className="sidenav-brand">
        <img src={logo} alt="The Hart Group Automotive" />
      </div>
      <nav aria-label="Sections">
        {links.map(([section, href, label, path]) => (
          <a key={section} href={href} aria-current={current === section ? "page" : undefined}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d={path} />
            </svg>
            <span>{label}</span>
            {counts[section] ? <em>{counts[section]}</em> : null}
          </a>
        ))}
      </nav>
      <div className="sidenav-user">
        <span className="avatar">{(user.name || user.email).slice(0, 1)}</span>
        <span className="sn-who">
          <b title={user.email}>{user.name || user.email}</b>
          <small>{user.role_label}</small>
        </span>
        <button type="button" className="signout" title="Sign out" aria-label="Sign out" onClick={onSignOut}>
          <Icon name="logout" />
        </button>
      </div>
    </aside>
  );
}
