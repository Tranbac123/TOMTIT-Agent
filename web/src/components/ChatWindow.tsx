import { useEffect, useRef } from 'react';
import type { MessageRecord } from '../api/types';
import { MessageBubble } from './MessageBubble';
import { LoadingIndicator } from './LoadingIndicator';
import { ErrorBanner } from './ErrorBanner';

interface ChatWindowProps {
  messages: MessageRecord[];
  sending: boolean;
  error: string | null;
  onDismissError: () => void;
  sessionSelected: boolean;
}

export function ChatWindow({
  messages,
  sending,
  error,
  onDismissError,
  sessionSelected,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  if (!sessionSelected) {
    return (
      <div className="chat-window chat-window-empty">
        <div className="chat-empty-state">
          <p className="chat-empty-title">Start a conversation</p>
          <p className="chat-empty-hint">Click <strong>New chat</strong> in the sidebar to begin.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-window">
      <div className="chat-messages">
        {messages.length === 0 && !sending && (
          <div className="chat-empty-state">
            <p className="chat-empty-hint">Send a message to start the conversation.</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {sending && <LoadingIndicator label="TomTit is thinking…" />}
        {error && <ErrorBanner message={error} onDismiss={onDismissError} />}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
