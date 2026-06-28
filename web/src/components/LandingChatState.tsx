import { ErrorBanner } from './ErrorBanner';
import { Composer } from './Composer';

interface LandingChatStateProps {
  onSend: (msg: string) => void;
  disabled: boolean;
  error: string | null;
  onDismissError: () => void;
}

export function LandingChatState({ onSend, disabled, error, onDismissError }: LandingChatStateProps) {
  return (
    <div className="landing-chat-state">
      {error && (
        <div className="landing-error">
          <ErrorBanner message={error} onDismiss={onDismissError} />
        </div>
      )}
      <h1 className="landing-title">What's on your mind today?</h1>
      <Composer disabled={disabled} onSend={onSend} variant="landing" />
    </div>
  );
}
