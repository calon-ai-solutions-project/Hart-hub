import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { chats as chatsApi, quotes as quotesApi } from "../api/client.js";

export const MAX_PICKS = 5;

const pounds = (pence) => (pence ? "£" + (pence / 100).toLocaleString("en-GB") : "");
const botSays = (body) => ({ role: "bot", kind: "text", body, payload: {}, created_at: new Date().toISOString() });

/** Everything the chat screen knows and can do: the chat list, the open chat, the ticked cars, sending. */
export default function useChat(notify, startFresh = false) {
  const [chats, setChats] = useState([]);
  const [current, setCurrent] = useState(null); // {id, title}
  const [messages, setMessages] = useState([]);
  const [picked, setPicked] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState(""); // what the assistant is doing right now, in words
  const [loading, setLoading] = useState(true); // a chat is being opened
  // The deposit box follows the deposit in the customer's request. Staff can type over it for one
  // quote; it follows the request again as soon as that deposit changes.
  const [deposit, setDeposit] = useState({ form: null, value: "", edited: false });
  const working = useRef(false);

  const followForm = useCallback((pence) => {
    setDeposit((now) => (pence === now.form && now.edited ? now : { form: pence, value: pounds(pence), edited: false }));
  }, []);

  const refreshList = useCallback(async () => {
    const list = await chatsApi.list();
    setChats(list);
    return list;
  }, []);

  const show = useCallback(
    (conversation) => {
      setCurrent({ id: conversation.id, title: conversation.title });
      setMessages(conversation.messages);
      setPicked(new Set());
      setDeposit({ form: conversation.deposit_pence ?? null, value: pounds(conversation.deposit_pence), edited: false });
      refreshList().catch(() => {});
    },
    [refreshList],
  );

  const open = useCallback(
    async (id) => {
      setLoading(true);
      try {
        show(await chatsApi.get(id));
      } catch (error) {
        notify(error.message);
      } finally {
        setLoading(false);
      }
    },
    [show, notify],
  );

  const startNew = useCallback(async () => {
    setLoading(true);
    try {
      show(await chatsApi.create());
    } catch (error) {
      notify(error.message);
    } finally {
      setLoading(false);
    }
  }, [show, notify]);

  // first load: the most recent chat, or a fresh one. Straight after signing in it is always a fresh
  // one (an untouched chat is re-used, so signing in does not pile up empty chats).
  const loaded = useRef(false);
  useEffect(() => {
    if (loaded.current) return; // once only, so a fresh chat is never created twice
    loaded.current = true;
    (async () => {
      try {
        const list = await chatsApi.list();
        let conversation = list.length ? await chatsApi.get(list[0].id) : await chatsApi.create();
        if (startFresh && conversation.messages.length > 1) conversation = await chatsApi.create();
        show(conversation);
      } catch (error) {
        notify(error.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [show, notify, startFresh]);

  /** Send `{text}`, `{form}` or `{remove}` to the open chat. */
  const send = useCallback(
    async (body) => {
      if (working.current || !current) return;
      working.current = true;
      setBusy(true);
      setTyping(body.remove ? "Updating the search" : "Searching the stock");
      try {
        const answer = await chatsApi.send(current.id, body);
        setMessages((now) => [...now, ...answer.messages]);
        setCurrent({ id: answer.conversation.id, title: answer.conversation.title });
        if ("deposit_pence" in answer.conversation) followForm(answer.conversation.deposit_pence);
        refreshList().catch(() => {});
      } catch (error) {
        setMessages((now) => [...now, botSays(error.message)]);
      } finally {
        working.current = false;
        setTyping("");
        setBusy(false);
      }
    },
    [current, followForm, refreshList],
  );

  const togglePick = useCallback(
    (id) => {
      if (!picked.has(id) && picked.size >= MAX_PICKS) {
        notify(`You can quote up to ${MAX_PICKS} cars at a time`);
        return;
      }
      const next = new Set(picked);
      next.has(id) ? next.delete(id) : next.add(id);
      setPicked(next);
    },
    [picked, notify],
  );

  const clearPicks = useCallback(() => setPicked(new Set()), []);

  const editDeposit = useCallback((value) => setDeposit((now) => ({ ...now, value, edited: true })), []);

  const getQuotes = useCallback(async () => {
    if (working.current || !current || !picked.size) return;
    working.current = true;
    setBusy(true);
    setTyping("Sending the cars to Codeweavers");
    try {
      // an untouched box sends nothing, so the server uses the request's deposit; a typed one (even "0") wins
      const amount = deposit.edited ? deposit.value.trim() || "0" : "";
      const answer = await quotesApi.request([...picked], amount, current.id);
      setPicked(new Set());
      setMessages((now) => [...now, ...answer.messages]);
      refreshList().catch(() => {});
    } catch (error) {
      setMessages((now) => [...now, botSays(error.message)]);
    } finally {
      working.current = false;
      setTyping("");
      setBusy(false);
    }
  }, [current, picked, deposit, refreshList]);

  /** Delete a chat. If it was the open one, move to the next chat, or start a fresh one. */
  const remove = useCallback(
    async (chat) => {
      await chatsApi.remove(chat.id);
      const left = chats.filter((other) => other.id !== chat.id);
      setChats(left);
      if (chat.id === current?.id) show(left.length ? await chatsApi.get(left[0].id) : await chatsApi.create());
    },
    [chats, current, show],
  );

  // what is narrowing the search right now: whatever the latest answer said
  const filters = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const found = messages[i].role === "bot" && messages[i].payload?.filters;
      if (found) return found;
    }
    return [];
  }, [messages]);

  const depositSource = deposit.edited
    ? "(changed for this quote)"
    : deposit.form
      ? "(from the request)"
      : "(none given)";

  return {
    chats, current, messages, picked, busy, typing, loading, filters,
    deposit: deposit.value, depositSource,
    open, startNew, send, togglePick, clearPicks, editDeposit, getQuotes, remove,
  };
}
