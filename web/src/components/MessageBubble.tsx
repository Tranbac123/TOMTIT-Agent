import type { MessageRecord } from '../api/types';

interface MessageBubbleProps {
  message: MessageRecord;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  return (
    <div className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className="message-role">{isUser ? 'You' : 'TomTit'}</div>
      <div className="message-content">
        {message.content || <span className="message-empty">(empty response)</span>}
      </div>
      {/* CONV-P0 P0-7E: raw memory provenance (UUIDs) is developer/debug metadata and is
          intentionally NOT rendered in normal chat. It remains on the API response
          (message.provenance) for debugging/tests. */}
      <div className="message-meta">
        <span className="message-time">{formatTime(message.created_at)}</span>
        {message.status && !isUser && (
          <span className={`message-status message-status-${message.status}`}>
            {message.status}
          </span>
        )}
      </div>
    </div>
  );
}
