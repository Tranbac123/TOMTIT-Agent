import { useState, useCallback } from 'react';
import type { RecallResult } from '../api/types';
import { ProvenancePanel } from './ProvenancePanel';
import { LoadingIndicator } from './LoadingIndicator';
import { ErrorBanner } from './ErrorBanner';

interface MemoryRecallPanelProps {
  sessionSelected: boolean;
  recalling: boolean;
  result: RecallResult | null;
  error: string | null;
  onRecall: (query: string) => void;
  onDismissError: () => void;
}

export function MemoryRecallPanel({
  sessionSelected,
  recalling,
  result,
  error,
  onRecall,
  onDismissError,
}: MemoryRecallPanelProps) {
  const [query, setQuery] = useState('');

  const handleSubmit = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed || recalling || !sessionSelected) return;
    onRecall(trimmed);
  }, [query, recalling, sessionSelected, onRecall]);

  return (
    <div className="recall-panel">
      <h2 className="recall-title">Memory Recall</h2>
      <p className="recall-hint">
        Query the TOMTIT-Agent memory for decisions, facts, and notes from previous sessions.
      </p>

      {!sessionSelected && (
        <p className="recall-no-session">Select or create a session before recalling memory.</p>
      )}

      <div className="recall-input-row">
        <textarea
          className="recall-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="What decision did we make about the database?"
          disabled={recalling || !sessionSelected}
          rows={2}
          aria-label="Memory recall query"
        />
        <button
          className="recall-submit"
          onClick={handleSubmit}
          disabled={recalling || !sessionSelected || !query.trim()}
        >
          Recall
        </button>
      </div>

      {recalling && <LoadingIndicator label="Recalling from memory…" />}
      {error && <ErrorBanner message={error} onDismiss={onDismissError} />}

      {result && !recalling && (
        <div className="recall-result">
          <div className="recall-result-status">
            Status: <span className={`recall-status-badge recall-status-${result.status}`}>{result.status}</span>
          </div>
          <div className="recall-result-content">
            {result.content || <span className="recall-empty">No matching memory found.</span>}
          </div>
          {result.provenance && result.provenance.length > 0 && (
            <ProvenancePanel items={result.provenance} />
          )}
        </div>
      )}
    </div>
  );
}
