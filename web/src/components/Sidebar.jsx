import { useMemo, useState } from "react";

import logo from "../assets/logo.png";
import { dateTimeOf, groupOf } from "../lib/format.js";
import Icon from "./Icon.jsx";

/** The list of chats: new, search, open, delete, and who is signed in. */
export default function Sidebar({ chats, currentId, open, user, onNew, onOpen, onDelete, onSignOut }) {
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const wanted = search.trim().toLowerCase();
    return chats.filter((chat) => !wanted || chat.title.toLowerCase().includes(wanted));
  }, [chats, search]);

  let heading = null;
  return (
    <aside className={`side${open ? " open" : ""}`} id="side">
      <div className="brand">
        <img className="logo" src={logo} alt="The Hart Group Automotive" />
      </div>
      <button className="new" id="new" type="button" onClick={onNew}>
        <Icon name="plus" />
        New chat
      </button>
      <label className="search">
        <span className="sr-only">Search your chats</span>
        <Icon name="search" />
        <input
          id="search"
          type="search"
          placeholder="Search chats"
          autoComplete="off"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>

      <nav className="list" id="list" aria-label="Your chats">
        {shown.length === 0 && <p className="none">{search.trim() ? "No chats match that search." : "No chats yet."}</p>}
        {shown.map((chat) => {
          const group = groupOf(chat.updated_at);
          const showHeading = group !== heading;
          heading = group;
          return (
            <div key={chat.id}>
              {showHeading && <h2>{group}</h2>}
              <div className="chat" aria-current={chat.id === currentId}>
                <button type="button" className="open" onClick={() => onOpen(chat.id)}>
                  <span className="name">{chat.title}</span>
                  <span className="when">{dateTimeOf(chat.updated_at)}</span>
                </button>
                <button
                  type="button"
                  className="delete"
                  title={`Delete chat: ${chat.title}`}
                  aria-label={`Delete chat: ${chat.title}`}
                  onClick={() => onDelete(chat)}
                >
                  <Icon name="trash" />
                </button>
              </div>
            </div>
          );
        })}
      </nav>

      <div className="who">
        <span className="avatar">{user.email.slice(0, 1)}</span>
        <span title={user.email}>{user.name || user.email}</span>
        <button type="button" className="signout" title="Sign out" aria-label="Sign out" onClick={onSignOut}>
          <Icon name="logout" />
        </button>
      </div>
    </aside>
  );
}
