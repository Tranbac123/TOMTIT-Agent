import type {
  Session,
  ChatResponse,
  SessionMessagesResponse,
  MemoryRecallResponse,
  Settings,
} from './types';

export class TomTitApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly httpStatus: number,
  ) {
    super(message);
    this.name = 'TomTitApiError';
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new TomTitApiError(
      'NETWORK_ERROR',
      'Cannot reach the backend. Is it running at the configured URL?',
      0,
    );
  }
  if (!res.ok) {
    let code = 'REQUEST_FAILED';
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json() as Record<string, unknown>;
      if (typeof body.error_code === 'string') code = body.error_code;
      if (typeof body.message === 'string') message = body.message;
    } catch {
      // ignore parse error — use defaults
    }
    throw new TomTitApiError(code, message, res.status);
  }
  return res.json() as Promise<T>;
}

export function createApiClient(settings: Settings) {
  const base = settings.api_base_url.replace(/\/$/, '');
  const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

  return {
    async health() {
      return request<{ ok: boolean; service: string; version: string }>(
        `${base}/api/health`,
      );
    },

    async createSession(title?: string) {
      return request<Session>(`${base}/api/sessions`, {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          user_id: settings.user_id,
          project_id: settings.project_id,
          ...(title ? { title } : {}),
        }),
      });
    },

    async listSessions() {
      return request<{ sessions: Session[] }>(`${base}/api/sessions`);
    },

    async getSessionMessages(sessionId: string) {
      return request<SessionMessagesResponse>(
        `${base}/api/sessions/${encodeURIComponent(sessionId)}/messages`,
      );
    },

    async sendChat(sessionId: string, message: string) {
      return request<ChatResponse>(`${base}/api/chat`, {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          message,
          user_id: settings.user_id,
          project_id: settings.project_id,
        }),
      });
    },

    async recallMemory(sessionId: string, query: string) {
      return request<MemoryRecallResponse>(`${base}/api/memory/recall`, {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          query,
          user_id: settings.user_id,
          project_id: settings.project_id,
        }),
      });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
