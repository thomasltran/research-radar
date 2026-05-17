import React, { useEffect, useRef } from 'react';

export function TerminalLog(props: { log?: string }) {
  const ref = useRef<HTMLPreElement | null>(null);
  const shouldFollowRef = useRef(true);

  useEffect(() => {
    const element = ref.current;
    if (!element || !shouldFollowRef.current) return;
    element.scrollTop = element.scrollHeight;
  }, [props.log]);

  return (
    <pre
      ref={ref}
      className="terminal-log"
      onScroll={(event) => {
        const element = event.currentTarget;
        shouldFollowRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
      }}
    >
      {props.log || 'No logs written yet.'}
    </pre>
  );
}
