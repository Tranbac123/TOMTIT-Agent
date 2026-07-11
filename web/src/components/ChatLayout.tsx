import type { Session, MessageRecord, RecallResult, Settings } from '../api/types';
import { Sidebar } from './Sidebar';
import { ChatWindow } from './ChatWindow';
import { Composer } from './Composer';
import { LandingChatState } from './LandingChatState';
import { MemoryRecallPanel } from './MemoryRecallPanel';
import { SettingsPanel } from './SettingsPanel';
import { DebugPanel } from './DebugPanel';
import type { ActiveView } from '../App';

interface ChatLayoutProps {
  sessions: Session[];
  selectedSessionId: string | null;
  messages: MessageRecord[];
  sending: boolean;
  chatError: string | null;
  view: ActiveView;
  sidebarCollapsed: boolean;
  recallResult: RecallResult | null;
  recalling: boolean;
  recallError: string | null;
  settings: Settings;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onSendMessage: (msg: string) => void;
  onLandingSend: (msg: string) => void;
  onSetView: (v: ActiveView) => void;
  onToggleSidebar: () => void;
  onRecall: (query: string) => void;
  onDismissChatError: () => void;
  onDismissRecallError: () => void;
  onSaveSettings: (s: Settings) => void;
  onNewChatWithTitle: (title?: string) => void;
}

export function ChatLayout({
  sessions,
  selectedSessionId,
  messages,
  sending,
  chatError,
  view,
  sidebarCollapsed,
  recallResult,
  recalling,
  recallError,
  settings,
  onNewChat,
  onSelectSession,
  onSendMessage,
  onLandingSend,
  onSetView,
  onToggleSidebar,
  onRecall,
  onDismissChatError,
  onDismissRecallError,
  onSaveSettings,
  onNewChatWithTitle,
}: ChatLayoutProps) {
  const showLanding = view === 'chat' && messages.length === 0 && !sending;

  return (
    <div className="app-layout">
      <Sidebar
        sessions={sessions}
        selectedId={selectedSessionId}
        collapsed={sidebarCollapsed}
        activeView={view}
        onNewChat={onNewChat}
        onSelectSession={onSelectSession}
        onSetView={onSetView}
        onToggleCollapse={onToggleSidebar}
        onNewChatWithTitle={onNewChatWithTitle}
      />

      <main className="app-main">
        {view === 'settings' ? (
          <SettingsPanel
            settings={settings}
            onSave={onSaveSettings}
            onCancel={() => onSetView('chat')}
          />
        ) : view === 'recall' ? (
          <MemoryRecallPanel
            sessionSelected={selectedSessionId !== null}
            recalling={recalling}
            result={recallResult}
            error={recallError}
            onRecall={onRecall}
            onDismissError={onDismissRecallError}
          />
        ) : showLanding ? (
          <LandingChatState
            onSend={onLandingSend}
            disabled={sending}
            error={chatError}
            onDismissError={onDismissChatError}
          />
        ) : (
          <>
            <ChatWindow
              messages={messages}
              sending={sending}
              error={chatError}
              onDismissError={onDismissChatError}
              sessionSelected={selectedSessionId !== null || sending}
            />
            <Composer
              disabled={sending || selectedSessionId === null}
              onSend={onSendMessage}
            />
            <DebugPanel
              sessionId={selectedSessionId}
              apiBaseUrl={settings.api_base_url}
            />
          </>
        )}
      </main>
    </div>
  );
}
