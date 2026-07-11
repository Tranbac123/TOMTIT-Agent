import { useCallback, useState } from 'react';

// CONV-P0 P0-8B: minimal debug console over the /api/debug endpoints. Self-contained
// (own fetch + local types) so it adds zero props to the existing chat prop chain and
// can be removed without touching any other component. Plain functional UI by design.

interface DebugFact {
  kind: string;
  value: string;
  active: boolean;
}

interface DebugMemory {
  session_id: string;
  summary: string;
  facts: DebugFact[];
}

interface DebugTrace {
  capability: string | null;
  route: string | null;
  safety_decision: string | null;
  tool_name: string | null;
  tool_ok: boolean | null;
  memory_diff: string[];
  final_answer: string;
}

interface DebugPanelProps {
  sessionId: string | null;
  apiBaseUrl: string;
}

export function DebugPanel({ sessionId, apiBaseUrl }: DebugPanelProps) {
  const [open, setOpen] = useState(false);
  const [memory, setMemory] = useState<DebugMemory | null>(null);
  const [trace, setTrace] = useState<DebugTrace | null>(null);
  const [status, setStatus] = useState<string>('');
  const base = apiBaseUrl.replace(/\/$/, '');

  const refreshMemory = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(
        `${base}/api/debug/memory?session_id=${encodeURIComponent(sessionId)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setMemory((await res.json()) as DebugMemory);
      setStatus('memory refreshed');
    } catch (err) {
      setStatus(`memory error: ${String(err)}`);
    }
  }, [base, sessionId]);

  const resetMemory = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${base}/api/debug/reset-memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { message: string };
      setStatus(body.message);
      await refreshMemory();
    } catch (err) {
      setStatus(`reset error: ${String(err)}`);
    }
  }, [base, sessionId, refreshMemory]);

  const refreshTrace = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(
        `${base}/api/debug/last-trace?session_id=${encodeURIComponent(sessionId)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { trace: DebugTrace | null };
      setTrace(body.trace);
      setStatus(body.trace ? 'trace refreshed' : 'no trace yet');
    } catch (err) {
      setStatus(`trace error: ${String(err)}`);
    }
  }, [base, sessionId]);

  if (!sessionId) return null;

  return (
    <div
      style={{
        borderTop: '1px solid var(--border-color, #ccc)',
        fontSize: 12,
        padding: '4px 12px',
      }}
    >
      <button type="button" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} Debug console
      </button>
      {open && (
        <div style={{ padding: '6px 0' }}>
          <div>
            session_id: <code>{sessionId}</code>
          </div>
          <div style={{ margin: '6px 0', display: 'flex', gap: 8 }}>
            <button type="button" onClick={refreshMemory}>Refresh memory</button>
            <button type="button" onClick={resetMemory}>Reset memory</button>
            <button type="button" onClick={refreshTrace}>Refresh trace</button>
          </div>
          {status && <div>status: {status}</div>}
          {trace && (
            <div style={{ marginTop: 6 }}>
              <div>capability: <code>{trace.capability ?? 'null'}</code></div>
              <div>route: <code>{trace.route ?? 'null'}</code></div>
              <div>safety: <code>{trace.safety_decision ?? 'null'}</code></div>
              <div>
                tool: <code>{trace.tool_name ?? 'null'}</code> / tool_ok:{' '}
                <code>{trace.tool_ok === null ? 'null' : String(trace.tool_ok)}</code>
              </div>
              <div>memory_diff: <code>{JSON.stringify(trace.memory_diff)}</code></div>
            </div>
          )}
          {memory && (
            <div style={{ marginTop: 6 }}>
              <div>memory: {memory.summary}</div>
              <ul style={{ margin: '4px 0 0 16px' }}>
                {memory.facts.map((fact, index) => (
                  <li key={`${fact.kind}-${fact.value}-${index}`}>
                    [{fact.kind}] {fact.value}
                    {fact.active ? '' : ' (retracted)'}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
