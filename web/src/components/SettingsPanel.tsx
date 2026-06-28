import { useState } from 'react';
import type { Settings } from '../api/types';

interface SettingsPanelProps {
  settings: Settings;
  onSave: (s: Settings) => void;
  onCancel: () => void;
}

export function SettingsPanel({ settings, onSave, onCancel }: SettingsPanelProps) {
  const [draft, setDraft] = useState<Settings>({ ...settings });

  return (
    <div className="settings-panel">
      <h2 className="settings-title">Settings</h2>

      <div className="settings-field">
        <label className="settings-label" htmlFor="setting-user-id">User ID</label>
        <input
          id="setting-user-id"
          className="settings-input"
          value={draft.user_id}
          onChange={(e) => setDraft((p) => ({ ...p, user_id: e.target.value }))}
          placeholder="local-user"
        />
      </div>

      <div className="settings-field">
        <label className="settings-label" htmlFor="setting-project-id">Project ID</label>
        <input
          id="setting-project-id"
          className="settings-input"
          value={draft.project_id}
          onChange={(e) => setDraft((p) => ({ ...p, project_id: e.target.value }))}
          placeholder="local-project"
        />
        <p className="settings-note">
          The backend runs in single-project mode. If the backend was started with
          <code>TOMTIT_MEMORY_PROJECT_ID</code>, this must match that value. Mismatched
          project_id will be rejected with <code>PROJECT_ID_REJECTED</code>.
        </p>
      </div>

      <div className="settings-field">
        <label className="settings-label" htmlFor="setting-api-url">Backend API Base URL</label>
        <input
          id="setting-api-url"
          className="settings-input"
          value={draft.api_base_url}
          onChange={(e) => setDraft((p) => ({ ...p, api_base_url: e.target.value }))}
          placeholder="http://localhost:8000"
        />
      </div>

      <div className="settings-actions">
        <button className="btn-primary" onClick={() => onSave(draft)}>Save</button>
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
