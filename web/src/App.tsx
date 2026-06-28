import { useState, useEffect, useCallback, useMemo } from 'react';
import { ChatLayout } from './components/ChatLayout';
import { createApiClient, TomTitApiError } from './api/client';
import type { Session, MessageRecord, RecallResult, Settings } from './api/types';

export type ActiveView = 'chat' | 'recall' | 'settings';

const STORAGE = {
  userId: 'tomtit_user_id',
  projectId: 'tomtit_project_id',
  apiBaseUrl: 'tomtit_api_base_url',
  selectedSessionId: 'tomtit_selected_session_id',
  sidebarCollapsed: 'tomtit_sidebar_collapsed',
} as const;

function loadSettings(): Settings {
  return {
    user_id: localStorage.getItem(STORAGE.userId) ?? 'local-user',
    project_id: localStorage.getItem(STORAGE.projectId) ?? 'local-project',
    api_base_url: localStorage.getItem(STORAGE.apiBaseUrl) ?? 'http://localhost:8000',
  };
}

function saveSettings(s: Settings) {
  localStorage.setItem(STORAGE.userId, s.user_id);
  localStorage.setItem(STORAGE.projectId, s.project_id);
  localStorage.setItem(STORAGE.apiBaseUrl, s.api_base_url);
}

function projectIdErrorMessage(code: string, base: string): string {
  if (code === 'PROJECT_ID_REJECTED' || code === 'PROJECT_ID_MISMATCH') {
    return (
      'This backend is configured for a different project_id. ' +
      'Use the configured project_id or restart the backend with the desired ' +
      'TOMTIT_MEMORY_PROJECT_ID. Check Settings to update your project_id.'
    );
  }
  return base;
}

function isSessionNotFound(e: unknown): boolean {
  if (e instanceof TomTitApiError) {
    return e.code === 'SESSION_NOT_FOUND' || e.httpStatus === 404;
  }
  return false;
}

const SESSION_EXPIRED_MSG =
  'Previous session expired — the backend was likely restarted. ' +
  'Send a new message to create a fresh session.';

export function App() {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    () => localStorage.getItem(STORAGE.selectedSessionId),
  );
  const [messages, setMessages] = useState<MessageRecord[]>([]);
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [view, setView] = useState<ActiveView>('chat');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem(STORAGE.sidebarCollapsed) === 'true',
  );
  const [recallResult, setRecallResult] = useState<RecallResult | null>(null);
  const [recalling, setRecalling] = useState(false);
  const [recallError, setRecallError] = useState<string | null>(null);

  const api = useMemo(() => createApiClient(settings), [settings]);

  useEffect(() => { saveSettings(settings); }, [settings]);

  // Persist selectedSessionId to localStorage (null removes it)
  useEffect(() => {
    if (selectedSessionId) {
      localStorage.setItem(STORAGE.selectedSessionId, selectedSessionId);
    } else {
      localStorage.removeItem(STORAGE.selectedSessionId);
    }
  }, [selectedSessionId]);

  useEffect(() => {
    localStorage.setItem(STORAGE.sidebarCollapsed, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  // Load sessions and silently clear any stale selectedSessionId not found on backend.
  useEffect(() => {
    api.listSessions()
      .then((r) => {
        const validIds = new Set(r.sessions.map((s) => s.session_id));
        setSessions(r.sessions);
        // Functional update reads current state — safe without adding selectedSessionId to deps.
        setSelectedSessionId((prev) => (prev && !validIds.has(prev) ? null : prev));
      })
      .catch(() => {});
  }, [api]);

  // Load messages for selected session; clear stale session gracefully on 404.
  useEffect(() => {
    if (!selectedSessionId) {
      setMessages([]);
      return;
    }
    api.getSessionMessages(selectedSessionId)
      .then((r) => setMessages(r.messages))
      .catch((e) => {
        setMessages([]);
        if (isSessionNotFound(e)) {
          setSelectedSessionId(null); // localStorage cleanup handled by the effect above
          setChatError(SESSION_EXPIRED_MSG);
        }
      });
  }, [selectedSessionId, api]);

  const handleNewChat = useCallback(
    async (title?: string) => {
      try {
        const session = await api.createSession(title);
        setSessions((prev) => [session, ...prev]);
        setSelectedSessionId(session.session_id);
        setMessages([]);
        setChatError(null);
        setView('chat');
      } catch (e) {
        const msg =
          e instanceof TomTitApiError
            ? projectIdErrorMessage(e.code, e.message)
            : 'Failed to create session.';
        setChatError(msg);
      }
    },
    [api],
  );

  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId);
    setChatError(null);
    setView('chat');
  }, []);

  // Normal send (from existing chat). Retries once with a fresh session on SESSION_NOT_FOUND.
  const handleSendMessage = useCallback(
    async (message: string) => {
      if (!selectedSessionId || sending) return;
      setSending(true);
      setChatError(null);
      let sessionId = selectedSessionId;
      try {
        try {
          await api.sendChat(sessionId, message);
        } catch (e) {
          if (isSessionNotFound(e)) {
            setSelectedSessionId(null);
            setMessages([]);
            const newSession = await api.createSession();
            setSessions((prev) => [newSession, ...prev]);
            setSelectedSessionId(newSession.session_id);
            sessionId = newSession.session_id;
            await api.sendChat(sessionId, message); // retry once; outer catch handles failure
          } else {
            throw e;
          }
        }
        const r = await api.getSessionMessages(sessionId);
        setMessages(r.messages);
      } catch (e) {
        const msg =
          e instanceof TomTitApiError
            ? projectIdErrorMessage(e.code, e.message)
            : 'An unexpected error occurred.';
        setChatError(msg);
      } finally {
        setSending(false);
      }
    },
    [selectedSessionId, sending, api],
  );

  // Landing send. Creates a session if none exists; retries with fresh session if stale.
  const handleLandingSend = useCallback(
    async (message: string) => {
      if (sending) return;
      setSending(true);
      setChatError(null);
      let sessionId = selectedSessionId;
      try {
        if (!sessionId) {
          const session = await api.createSession();
          setSessions((prev) => [session, ...prev]);
          setSelectedSessionId(session.session_id);
          sessionId = session.session_id;
        }
        try {
          await api.sendChat(sessionId, message);
        } catch (e) {
          if (isSessionNotFound(e)) {
            // selectedSessionId was loaded from localStorage and is stale — recover
            setSelectedSessionId(null);
            setMessages([]);
            const newSession = await api.createSession();
            setSessions((prev) => [newSession, ...prev]);
            setSelectedSessionId(newSession.session_id);
            sessionId = newSession.session_id;
            await api.sendChat(sessionId, message); // retry once; outer catch handles failure
          } else {
            throw e;
          }
        }
        const r = await api.getSessionMessages(sessionId);
        setMessages(r.messages);
      } catch (e) {
        const msg =
          e instanceof TomTitApiError
            ? projectIdErrorMessage(e.code, e.message)
            : 'An unexpected error occurred.';
        setChatError(msg);
      } finally {
        setSending(false);
      }
    },
    [selectedSessionId, sending, api],
  );

  const handleRecall = useCallback(
    async (query: string) => {
      if (!selectedSessionId || recalling) return;
      setRecalling(true);
      setRecallError(null);
      setRecallResult(null);
      try {
        const r = await api.recallMemory(selectedSessionId, query);
        setRecallResult(r.result);
      } catch (e) {
        if (isSessionNotFound(e)) {
          setSelectedSessionId(null);
          setMessages([]);
          setRecallError(SESSION_EXPIRED_MSG);
        } else {
          const msg =
            e instanceof TomTitApiError
              ? projectIdErrorMessage(e.code, e.message)
              : 'Memory recall failed.';
          setRecallError(msg);
        }
      } finally {
        setRecalling(false);
      }
    },
    [selectedSessionId, recalling, api],
  );

  const handleSaveSettings = useCallback((newSettings: Settings) => {
    setSettings(newSettings);
    setSessions([]);
    setSelectedSessionId(null);
    setMessages([]);
    setChatError(null);
    setRecallResult(null);
    setView('chat');
  }, []);

  return (
    <ChatLayout
      sessions={sessions}
      selectedSessionId={selectedSessionId}
      messages={messages}
      sending={sending}
      chatError={chatError}
      view={view}
      sidebarCollapsed={sidebarCollapsed}
      recallResult={recallResult}
      recalling={recalling}
      recallError={recallError}
      settings={settings}
      onNewChat={() => handleNewChat()}
      onSelectSession={handleSelectSession}
      onSendMessage={handleSendMessage}
      onSetView={setView}
      onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
      onRecall={handleRecall}
      onLandingSend={handleLandingSend}
      onDismissChatError={() => setChatError(null)}
      onDismissRecallError={() => setRecallError(null)}
      onSaveSettings={handleSaveSettings}
      onNewChatWithTitle={(title) => handleNewChat(title)}
    />
  );
}
