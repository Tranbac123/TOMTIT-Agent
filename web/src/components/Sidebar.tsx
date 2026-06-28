import type { Session } from '../api/types';
import { ConversationList } from './ConversationList';
import type { ActiveView } from '../App';
import { brandAssets, navIcons } from '../assets/icons/index';

interface SidebarProps {
  sessions: Session[];
  selectedId: string | null;
  collapsed: boolean;
  activeView: ActiveView;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onSetView: (v: ActiveView) => void;
  onToggleCollapse: () => void;
  onNewChatWithTitle: (title?: string) => void;
}

interface NavButtonProps {
  label: string;
  iconSrc: string;
  active?: boolean;
  onClick: () => void;
}

function NavButton({ label, iconSrc, active, onClick }: NavButtonProps) {
  return (
    <button
      className={`sidebar-nav-btn ${active ? 'sidebar-nav-btn-active' : ''}`}
      onClick={onClick}
      title={label}
    >
      <span className="sidebar-nav-icon">
        <img src={iconSrc} alt="" aria-hidden="true" className="nav-icon" />
      </span>
      <span className="sidebar-nav-label">{label}</span>
    </button>
  );
}

export function Sidebar({
  sessions,
  selectedId,
  collapsed,
  activeView,
  onNewChat,
  onSelectSession,
  onSetView,
  onToggleCollapse,
  onNewChatWithTitle,
}: SidebarProps) {
  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <img
            src={brandAssets.tomtitMark}
            alt="TomTit"
            className="brand-mark"
          />
          {!collapsed && <span className="sidebar-wordmark">TomTit</span>}
        </div>
        <button
          className="sidebar-collapse-btn"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      <nav className="sidebar-nav">
        <NavButton label="New chat" iconSrc={navIcons.newChat} onClick={onNewChat} />
        <NavButton label="Search" iconSrc={navIcons.search} onClick={() => onSetView('chat')} />
        <NavButton
          label="Memory"
          iconSrc={navIcons.memory}
          active={activeView === 'recall'}
          onClick={() => onSetView('recall')}
        />
        <NavButton label="Skills" iconSrc={navIcons.skills} onClick={() => onSetView('chat')} />
        <NavButton label="Projects" iconSrc={navIcons.projects} onClick={() => onSetView('chat')} />
        <NavButton label="Sessions" iconSrc={navIcons.sessions} onClick={() => onSetView('chat')} />
        <NavButton label="Provenance" iconSrc={navIcons.provenance} onClick={() => onSetView('chat')} />
        <NavButton
          label="Settings"
          iconSrc={navIcons.more}
          active={activeView === 'settings'}
          onClick={() => onSetView('settings')}
        />
      </nav>

      {!collapsed && (
        <div className="sidebar-conversations">
          <ConversationList
            sessions={sessions}
            selectedId={selectedId}
            onSelect={onSelectSession}
            onNewChat={onNewChatWithTitle}
          />
        </div>
      )}
    </aside>
  );
}
