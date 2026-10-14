import { useCallback, useEffect, useRef, useState } from "react";

import useChat, { MAX_PICKS } from "../hooks/useChat.js";
import { ConfirmDelete, Toast } from "./Dialogs.jsx";
import { Composer, FilterBar, SelectionBar } from "./Dock.jsx";
import Icon from "./Icon.jsx";
import Message, { ThreadLoading, TypingRow } from "./Message.jsx";
import ChatList from "./ChatList.jsx";
import SideNav from "./SideNav.jsx";

const TOAST_MS = 2600;

/** The stock chat, laid out like WhatsApp enquiries: the menu, the chat history, and the open chat. */
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
  const [deleting, setDeleting] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
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
      <div className="crm">
        <SideNav user={user} current="chat" onSignOut={onSignOut} />
        <div className="crm-main wa-page">
          <header className="wa-top">
            <div className="wa-title">
              <h1>Stock chat</h1>
              <span className="sim-pill">
                <i className={app.ai_enabled ? "on" : ""} /> {app.ai_enabled ? "AI ranking on" : "Rule-based matching"}
              </span>
            </div>
            <button className="btn primary" id="new" type="button" onClick={chat.startNew}>
              + New chat
            </button>
          </header>

          <div className="chat-body">
            <ChatList chats={chat.chats} currentId={chat.current?.id} onOpen={chat.open} onDelete={setDeleting} />

        <section className="main chat-pane">
          <header className="top">
            <h1 id="title">{chat.current?.title || "New chat"}</h1>
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
            {(chat.busy || chat.loading) && <div className="progress" aria-hidden="true" />}
          </header>

          <div className="thread" id="scroller" ref={scroller}>
            <div className="thread-inner" id="thread" aria-live="polite" key={chat.current?.id}>
              {chat.loading && chat.messages.length === 0 && <ThreadLoading />}
              {chat.messages.map((message, index) => (
                <Message
                  key={message.id || index}
                  message={message}
                  latest={index === latestBot && index === chat.messages.length - 1}
                  picked={chat.picked}
                  onTogglePick={chat.togglePick}
                  onSend={chat.send}
                />
              ))}
              {chat.typing && <TypingRow label={chat.typing} />}
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
        </div>
      </div>

      <ConfirmDelete chat={deleting} busy={deleteBusy} onCancel={() => setDeleting(null)} onConfirm={confirmDelete} />
      <Toast message={toast} />
    </>
  );
}
