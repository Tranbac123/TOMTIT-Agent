import type { ProvenanceItem } from '../api/types';

interface ProvenancePanelProps {
  items: ProvenanceItem[];
}

export function ProvenancePanel({ items }: ProvenancePanelProps) {
  const populated = items.filter(
    (p) => p.memory_id ?? p.evidence_ref ?? p.source_task_id,
  );
  if (populated.length === 0) return null;

  return (
    <div className="provenance-panel">
      <p className="provenance-heading">Provenance</p>
      {populated.map((item, i) => (
        <div key={i} className="provenance-item">
          {item.memory_id && (
            <span className="provenance-badge">
              <span className="provenance-label">memory</span> {item.memory_id}
            </span>
          )}
          {item.evidence_ref && (
            <span className="provenance-badge">
              <span className="provenance-label">evidence</span> {item.evidence_ref}
            </span>
          )}
          {item.source_task_id && (
            <span className="provenance-badge">
              <span className="provenance-label">task</span> {item.source_task_id}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
