import { useEffect, useState } from "react";

import { quotes as quotesApi } from "../api/client.js";
import QuoteCard from "./QuoteCard.jsx";

const POLL_MS = 4000;
const waiting = (quote) => quote.status === "pending" || quote.status === "running";

/** The quotes of one "finance quotes" message. Each fills in as it arrives from Codeweavers. */
export default function QuoteList({ ids, onPreview }) {
  const [quotes, setQuotes] = useState(null);
  const [failed, setFailed] = useState(false);
  const key = ids.join(",");

  useEffect(() => {
    let stopped = false;
    let timer;
    async function load() {
      try {
        const answer = await quotesApi.status(key.split(","));
        if (stopped) return;
        setQuotes(answer.quotes);
        if (answer.quotes.some(waiting)) timer = setTimeout(load, POLL_MS);
      } catch {
        if (!stopped) setFailed(true);
      }
    }
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [key]);

  if (failed) return <div className="bubble">Could not load the quotes. Reopen this chat to try again.</div>;
  if (!quotes) return null;
  return (
    <div className="cards results">
      {quotes.map((quote) => (
        <QuoteCard key={quote.id} quote={quote} onPreview={onPreview} />
      ))}
    </div>
  );
}
