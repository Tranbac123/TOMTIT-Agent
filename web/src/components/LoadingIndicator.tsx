export function LoadingIndicator({ label = 'Thinking…' }: { label?: string }) {
  return (
    <div className="loading-indicator" aria-live="polite" aria-label={label}>
      <span className="loading-dot" />
      <span className="loading-dot" />
      <span className="loading-dot" />
      <span className="loading-label">{label}</span>
    </div>
  );
}
