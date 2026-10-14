import { timeOf } from "../lib/format.js";
import CarCard from "./CarCard.jsx";
import QuoteList from "./QuoteList.jsx";

/** One message in the thread: plain text, car options, or finance quotes. */
export default function Message({ message, latest, picked, onTogglePick, onSend, onPreview }) {
  const payload = message.payload || {};

  return (
    <div className={`row ${message.role}`}>
      {/* an older chat may still open with the enquiry form message: it shows as its plain greeting */}
      <div className="bubble">
        {message.body}
        {message.kind === "options" && (
          <ul className="notes">
            {payload.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>

      {message.kind === "options" && payload.cards.length > 0 && (
        <div className="cards results">
          {payload.cards.map((option, index) => (
            <CarCard
              key={option.customer.id}
              option={option}
              rank={index + 1}
              picked={picked.has(option.customer.id)}
              onToggle={onTogglePick}
            />
          ))}
        </div>
      )}

      {message.kind === "quotes" && <QuoteList ids={payload.quote_ids} onPreview={onPreview} />}

      {/* one-tap next steps, only under the latest answer */}
      {latest && payload.suggestions?.length > 0 && (
        <div className="chips">
          {payload.suggestions.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => onSend({ text: suggestion })}>
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="stamp">{timeOf(message.created_at)}</div>
    </div>
  );
}

/** The assistant is working: three dots and what it is doing. */
export function TypingRow({ label }) {
  return (
    <div className="row bot" id="typing" role="status">
      <div className="bubble working">
        <span className="typing">
          <i />
          <i />
          <i />
        </span>
        {label && <span className="working-label">{label}…</span>}
      </div>
    </div>
  );
}

/** Placeholder rows while a chat is being opened. */
export function ThreadLoading() {
  return (
    <div className="thread-loading" role="status" aria-label="Loading the chat">
      <div className="skeleton short" />
      <div className="skeleton tall" />
      <div className="skeleton right" />
      <div className="skeleton" />
    </div>
  );
}
