import { useEffect, useRef, useState } from "react";

import { photos as photoApi } from "../api/client.js";
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

/** Every photo of a car, for staff, with which ones customers see. Damage photos (labelled by the platform)
 *  are always hidden from customers, because Hart repairs damage before handover; any other photo can be
 *  hidden or shown here. */
export function PhotosDialog({ car, onClose }) {
  const [list, setList] = useState(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (!car) return;
    setList(null);
    setProblem("");
    photoApi.list(car.id).then((data) => setList(data.photos)).catch((error) => setProblem(error.message));
  }, [car]);

  async function toggle(photo) {
    setBusy(photo.position);
    setProblem("");
    try {
      const saved = await photoApi.setHidden(car.id, photo.position, !photo.hidden);
      setList((now) => now.map((p) => (p.position === saved.position ? saved : p)));
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(null);
    }
  }

  const shown = (list || []).filter((p) => p.shown_to_customers).length;
  return (
    <Modal open={Boolean(car)} onClose={onClose} className="photos-dialog" labelledBy="photos-title">
      <header>
        <div>
          <h2 id="photos-title">{car?.title}</h2>
          <p>
            {list ? `${shown} of ${list.length} photos shown to customers.` : "Loading photos…"} Damage photos are
            never shown: Hart repairs damage before handover.
          </p>
        </div>
        <button type="button" className="close" aria-label="Close" onClick={onClose}>×</button>
      </header>
      {problem && <div className="login-error">{problem}</div>}
      <div className="photos-grid">
        {(list || []).map((photo) => (
          <figure key={photo.position} className={photo.shown_to_customers ? "" : "off"}>
            {photo.url ? <img src={photo.url} alt={photo.label || `Photo ${photo.position}`} loading="lazy" />
                       : <div className="no-file">Not stored yet</div>}
            <figcaption>
              {photo.damage ? (
                <span className="badge damage">Damage · hidden</span>
              ) : photo.hidden ? (
                <span className="badge hidden">Hidden</span>
              ) : (
                <span className="badge shown">Shown</span>
              )}
              {!photo.damage && (
                <button type="button" className="btn ghost small" disabled={busy === photo.position}
                        onClick={() => toggle(photo)}>
                  {photo.hidden ? "Show" : "Hide"}
                </button>
              )}
            </figcaption>
            {photo.label && <small title={photo.label}>{photo.label.replaceAll("_", " ")}</small>}
          </figure>
        ))}
      </div>
    </Modal>
  );
}
