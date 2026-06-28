import type { Session } from '../api/types';
import { itemIcons } from '../assets/icons/index';

const PINNED_ITEMS = [
  'Build TOMTIT web UI',
  'Kiến trúc TOMTIT-Agent',
  'Kiến trúc TOMTIT-Memory',
  'Kiến trúc TOMTIT-Memory 2',
  'AI tự tiến hoá',
];

interface ConversationListProps {
  sessions: Session[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNewChat: (title?: string) => void;
}

function sessionLabel(s: Session): string {
  return s.title ?? `Session ${s.session_id.slice(0, 8)}`;
}

export function ConversationList({
  sessions,
  selectedId,
  onSelect,
  onNewChat,
}: ConversationListProps) {
  return (
    <div className="conv-list">
      {sessions.length > 0 && (
        <div className="conv-section">
          <p className="conv-section-label">Recent</p>
          {sessions.map((s) => (
            <button
              key={s.session_id}
              className={`conv-item ${s.session_id === selectedId ? 'conv-item-selected' : ''}`}
              onClick={() => onSelect(s.session_id)}
              title={sessionLabel(s)}
            >
              <img src={itemIcons.folder} alt="" aria-hidden="true" className="conversation-icon" />
              <span className="conv-item-label">{sessionLabel(s)}</span>
            </button>
          ))}
        </div>
      )}

      <div className="conv-section">
        <p className="conv-section-label">Pinned</p>
        {PINNED_ITEMS.map((title) => (
          <button
            key={title}
            className="conv-item conv-item-pinned"
            onClick={() => onNewChat(title)}
            title={`Start: ${title}`}
          >
            <img src={itemIcons.folder} alt="" aria-hidden="true" className="conversation-icon" />
            <span className="conv-item-label">{title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
