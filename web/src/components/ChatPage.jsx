import { useCallback, useEffect, useRef, useState } from "react";

import useChat, { MAX_PICKS } from "../hooks/useChat.js";
import { ConfirmDelete, PdfViewer, Toast } from "./Dialogs.jsx";
import { Composer, FilterBar, SelectionBar } from "./Dock.jsx";
import Icon from "./Icon.jsx";
import Message, { TypingRow } from "./Message.jsx";
import Sidebar from "./Sidebar.jsx";

const TOAST_MS = 2600;

/** The staff chat screen: chats on the left, the open chat in the middle, the composer at the bottom. */
export default function ChatPage({ user, app, startFresh, onSignOut }) {
  const [toast, setToast] = useState("");
  const toastTimer = useRef(null);
  const notify = useCallback((message) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), TOAST_MS);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const chat = useChat(notify, startFresh);
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [previewing, setPreviewing] = useState(null);
  const scroller = useRef(null);

  // new messages, and the typing dots, bring the thread to the bottom
  useEffect(() => {
    const node = scroller.current;
    node.scrollTop = node.scrollHeight;
  }, [chat.messages, chat.typing]);

  // the selection bar takes room from the thread: stay at the bottom if that is where the reader was
  const hasPicks = chat.picked.size > 0;
  useEffect(() => {
    const node = scroller.current;
    if (hasPicks && node.scrollHeight - node.scrollTop - node.clientHeight < 160) node.scrollTop = node.scrollHeight;
  }, [hasPicks]);

  async function confirmDelete() {
    setDeleteBusy(true);
    try {
      await chat.remove(deleting);
      notify("Chat deleted");
    } catch (error) {
      notify(error.message);
    } finally {
      setDeleting(null);
      setDeleteBusy(false);
    }
  }

  const latestBot = chat.messages.findLastIndex((message) => message.role === "bot");
  const currentChat = chat.chats.find((other) => other.id === chat.current?.id);

  return (
    <>
      <div className="app">
        <Sidebar
          chats={chat.chats}
          currentId={chat.current?.id}
          open={menuOpen}
          user={user}
          onNew={() => {
            setMenuOpen(false);
            chat.startNew();
          }}
          onOpen={(id) => {
            setMenuOpen(false);
            chat.open(id);
          }}
          onDelete={setDeleting}
          onSignOut={onSignOut}
        />

        <section className="main">
          <header className="top">
            <button
              className="icon-btn menu"
              id="menu"
              type="button"
              aria-label="Show chats"
              onClick={() => setMenuOpen((now) => !now)}
            >
              <Icon name="menu" />
            </button>
            <h1 id="title">{chat.current?.title || "New chat"}</h1>
            <span
              className={`badge hide-sm${app.ai_enabled ? " on" : ""}`}
              title={
                app.ai_enabled
                  ? "AI reads free text and ranks the shortlist"
                  : "Set OPENROUTER_API_KEY and OPENROUTER_MODEL to turn AI on"
              }
            >
              <i />
              {app.ai_enabled ? "AI ranking on" : "Rule-based matching"}
            </span>
            <button
              className="icon-btn danger"
              id="delete-current"
              type="button"
              aria-label="Delete this chat"
              title="Delete this chat"
              onClick={() => currentChat && setDeleting(currentChat)}
            >
              <Icon name="trash" />
            </button>
          </header>

          <div className="thread" id="scroller" ref={scroller}>
            <div className="thread-inner" id="thread" aria-live="polite" key={chat.current?.id}>
              {chat.messages.map((message, index) => (
                <Message
                  key={message.id || index}
                  message={message}
                  latest={index === latestBot && index === chat.messages.length - 1}
                  picked={chat.picked}
                  onTogglePick={chat.togglePick}
                  onSend={chat.send}
                  onPreview={setPreviewing}
                />
              ))}
              {chat.typing && <TypingRow />}
            </div>
          </div>

          <div className="dock">
            <div className="dock-inner">
              <SelectionBar
                count={chat.picked.size}
                max={MAX_PICKS}
                deposit={chat.deposit}
                depositSource={chat.depositSource}
                term={app.quote_term_months}
                busy={chat.busy}
                onDeposit={chat.editDeposit}
                onClear={chat.clearPicks}
                onQuote={chat.getQuotes}
              />
              <FilterBar filters={chat.filters} onRemove={(key) => chat.send({ remove: key })} />
              <Composer busy={chat.busy} onSend={(text) => chat.send({ text })} />
              <div className="foot">
                Enter to send · Shift + Enter for a new line · Finance figures always come from Codeweavers
              </div>
            </div>
          </div>
        </section>
      </div>

      <ConfirmDelete chat={deleting} busy={deleteBusy} onCancel={() => setDeleting(null)} onConfirm={confirmDelete} />
      <PdfViewer quote={previewing} onClose={() => setPreviewing(null)} />
      <Toast message={toast} />
    </>
  );
}
