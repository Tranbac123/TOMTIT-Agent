export interface Settings {
  user_id: string;
  project_id: string;
  api_base_url: string;
}

export interface Session {
  session_id: string;
  user_id: string;
  project_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProvenanceItem {
  memory_id?: string;
  evidence_ref?: string;
  source_task_id?: string;
}

export interface MessageRecord {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  provenance: ProvenanceItem[];
  sources: Record<string, unknown>[];
  status?: string;
}

export interface RecallResult {
  content: string;
  status: string;
  provenance: ProvenanceItem[];
  sources: Record<string, unknown>[];
}

export interface ChatResponse {
  session_id: string;
  assistant_message: MessageRecord;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: MessageRecord[];
}

export interface MemoryRecallResponse {
  session_id: string;
  result: RecallResult;
}
