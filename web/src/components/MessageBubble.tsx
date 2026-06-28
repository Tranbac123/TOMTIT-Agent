import type { MessageRecord } from '../api/types';
import { ProvenancePanel } from './ProvenancePanel';

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
      {!isUser && message.provenance && message.provenance.length > 0 && (
        <ProvenancePanel items={message.provenance} />
      )}
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
