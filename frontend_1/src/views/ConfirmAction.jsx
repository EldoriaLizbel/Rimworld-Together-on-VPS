"use client";

import { useEffect, useRef, useId } from "react";

export default function ConfirmAction({ c, title, message, label, onCancel, onConfirm }) {
  const dialog = useRef(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return (
    <dialog ref={dialog} className={`rt-dialog rounded-xl ${c.modal}`}
      aria-labelledby={id} aria-describedby={`${id}-message`}
      onCancel={(event) => { event.preventDefault(); onCancel(); }}>
      <div className="grid gap-3 p-5">
        <h2 id={id} className="text-lg font-semibold">{title}</h2>
        <p id={`${id}-message`} className={`text-sm ${c.label}`}>{message}</p>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" autoFocus onClick={onCancel} className={`rounded-lg px-4 text-sm ${c.btnGhost}`}>Cancel</button>
          <button type="button" onClick={onConfirm} className="rt-button rt-danger-button">{label}</button>
        </div>
      </div>
    </dialog>
  );
}
