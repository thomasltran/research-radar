import React from 'react';

export function ConfirmModal(props: {
  title: string;
  body: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={props.onCancel}>
      <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" onClick={(event) => event.stopPropagation()}>
        <h2 id="confirm-title">{props.title}</h2>
        <p>{props.body}</p>
        <div className="confirm-actions">
          <button className="ghost-button" onClick={props.onCancel}>Cancel</button>
          <button className="ghost-button danger-button" onClick={props.onConfirm}>{props.confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
