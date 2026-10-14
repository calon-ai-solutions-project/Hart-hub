import { useMemo, useState } from "react";

import { groupOf, timeOf } from "../lib/format.js";
import Icon from "./Icon.jsx";

/** The chat history: search, grouped by day, open or delete a chat. */
export default function ChatList({ chats, currentId, onOpen, onDelete }) {
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const wanted = search.trim().toLowerCase();
    return chats.filter((chat) => !wanted || chat.title.toLowerCase().includes(wanted));
  }, [chats, search]);

  let heading = null;
  return (
    <section className="wa-list chat-history" aria-label="Your chats">
      <label className="wa-search">
        <span className="sr-only">Search your chats</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search chats"
               autoComplete="off" />
      </label>
      <div className="wa-rows">
        {shown.length === 0 && (
          <div className="wa-list-empty">
            <b>{search.trim() ? "No match" : "No chats yet"}</b>
            <span>{search.trim() ? "No chat has that name." : "Start one with “New chat”."}</span>
          </div>
        )}
        {shown.map((chat) => {
          const group = groupOf(chat.updated_at);
          const showHeading = group !== heading;
          heading = group;
          return (
            <div key={chat.id}>
              {showHeading && <h2 className="history-day">{group}</h2>}
              <div className={`history-row${chat.id === currentId ? " on" : ""}`}>
                <button type="button" className="history-open" onClick={() => onOpen(chat.id)}>
                  <span className="history-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M4 5h16v11H8l-4 4zM8 9h8M8 12h5" /></svg>
                  </span>
                  <span className="history-main">
                    <b>{chat.title}</b>
                    <small>{group === "Today" || group === "Yesterday" ? timeOf(chat.updated_at) : group}</small>
                  </span>
                </button>
                <button type="button" className="history-delete" title={`Delete chat: ${chat.title}`}
                        aria-label={`Delete chat: ${chat.title}`} onClick={() => onDelete(chat)}>
                  <Icon name="trash" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
