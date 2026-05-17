import React from 'react';
import type { View } from '../../types';

export function NavButton(props: {
  view: View;
  active: View;
  icon: React.ReactNode;
  label: string;
  count?: number;
  onClick: (view: View) => void;
}) {
  return (
    <button
      className={props.active === props.view ? 'nav-button active' : 'nav-button'}
      onClick={() => props.onClick(props.view)}
      aria-current={props.active === props.view ? 'page' : undefined}
    >
      {props.icon}
      <span className="nav-label">{props.label}</span>
      {props.count !== undefined && <span className="nav-count">{props.count}</span>}
    </button>
  );
}
