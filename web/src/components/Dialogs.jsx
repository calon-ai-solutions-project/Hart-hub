import { useEffect, useRef } from "react";

import Icon from "./Icon.jsx";

/** A native <dialog> that opens and closes with a prop. Clicking the backdrop closes it. */
function Modal({ open, onClose, className, labelledBy, children }) {
  const node = useRef(null);
  useEffect(() => {
    const dialog = node.current;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={node}
      className={className}
      aria-labelledby={labelledBy}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === node.current) onClose();
      }}
    >
      {open && children}
    </dialog>
  );
}

export function ConfirmDelete({ chat, busy, onCancel, onConfirm }) {
  return (
    <Modal open={Boolean(chat)} onClose={onCancel} className="confirm" labelledBy="confirm-title">
      <div className="inner">
        <div className="sign">
          <Icon name="trash" />
        </div>
        <h2 id="confirm-title">Delete this chat?</h2>
        <p>
          <b id="confirm-name">“{chat?.title}”</b> and its messages will be removed for good. Finance quotes already
          fetched stay on record.
        </p>
      </div>
      <div className="acts">
        <button type="button" className="btn ghost" id="confirm-cancel" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn danger" id="confirm-delete" disabled={busy} onClick={onConfirm}>
          Delete chat
        </button>
      </div>
    </Modal>
  );
}

export function Toast({ message }) {
  return (
    <div className={`toast${message ? " show" : ""}`} id="toast" role="status">
      {message}
    </div>
  );
}
