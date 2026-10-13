import { useRef } from "react";

import Icon from "./Icon.jsx";

/** The bar that appears once cars are ticked: how many, the deposit, the term, and the quote button. */
export function SelectionBar({ count, max, deposit, depositSource, term, busy, onDeposit, onClear, onQuote }) {
  if (count === 0) return null;
  return (
    <div className="selection" id="selection">
      <b id="selected-count">
        {count} car{count === 1 ? "" : "s"} selected{count >= max ? " (maximum)" : ""}
      </b>
      <label>
        Deposit
        <input
          id="deposit"
          inputMode="decimal"
          placeholder="£0"
          aria-label="Deposit"
          value={deposit}
          onChange={(event) => onDeposit(event.target.value)}
        />
      </label>
      <span className="dim" id="deposit-source">
        {depositSource}
      </span>
      <span className="dim">Term {term} months</span>
      <span className="fill" />
      <button type="button" className="clear" id="clear-selection" onClick={onClear}>
        Clear
      </button>
      <button type="button" className="btn primary small" id="get-quotes" disabled={busy} onClick={onQuote}>
        Get finance quotes
      </button>
    </div>
  );
}

/** What is narrowing the search right now. The × on each removes that one filter. */
export function FilterBar({ filters, onRemove }) {
  return (
    <div className="filters" id="filters" aria-label="Current filters">
      {filters.length > 0 && <span className="label">Looking for</span>}
      {filters.map((filter) => (
        <span className="filter" key={filter.key}>
          {filter.label}
          <button
            type="button"
            title={`Remove ${filter.label}`}
            aria-label={`Remove ${filter.label}`}
            onClick={() => onRemove(filter.key)}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}

/** The message box. Enter sends; Shift + Enter starts a new line. */
export function Composer({ busy, onSend }) {
  const box = useRef(null);

  function send() {
    const value = box.current.value.trim();
    if (!value) return;
    box.current.value = "";
    box.current.style.height = "";
    onSend(value);
  }

  return (
    <form
      className="composer-box"
      id="composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <textarea
        id="text"
        ref={box}
        rows={1}
        placeholder="Ask for a car, or refine the results…"
        aria-label="Message"
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            send();
          }
        }}
        onInput={(event) => {
          event.target.style.height = "";
          event.target.style.height = `${Math.min(event.target.scrollHeight, 140)}px`;
        }}
      />
      <button className="send" id="send" aria-label="Send" disabled={busy}>
        <Icon name="send" />
      </button>
    </form>
  );
}
