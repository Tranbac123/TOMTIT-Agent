import {
  useState,
  useRef,
  useCallback,
  useLayoutEffect,
  type KeyboardEvent,
} from 'react';

// Max visual height of the auto-growing composer; past this it scrolls internally.
const MAX_COMPOSER_HEIGHT = 200;

interface ComposerProps {
  disabled: boolean;
  onSend: (message: string) => void;
  variant?: 'default' | 'landing';
}

export function Composer({ disabled, onSend, variant = 'default' }: ComposerProps) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize: reset to one line, then grow to fit content up to the max height.
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT)}px`;
  }, [text]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    textareaRef.current?.focus();
  }, [text, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  if (variant === 'landing') {
    return (
      <div className="composer composer-landing">
        <button
          className="composer-plus"
          type="button"
          disabled
          title="Attachments not available yet"
          aria-label="Attachments not available yet"
          aria-disabled="true"
        >
          +
        </button>
        <textarea
          ref={textareaRef}
          className="composer-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What's on your mind today?"
          disabled={disabled}
          rows={1}
          aria-label="Message input"
        />
        <button
          className="composer-send composer-send-icon"
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          aria-label="Send message"
        >
          ↑
        </button>
      </div>
    );
  }

  return (
    <div className="composer">
      <div className="composer-inner">
        <textarea
          ref={textareaRef}
          className="composer-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? 'Waiting for response…' : 'Message TomTit — Enter to send, Shift+Enter for newline'}
          disabled={disabled}
          rows={1}
          aria-label="Message input"
        />
        <button
          className="composer-send"
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          aria-label="Send message"
        >
          Send
        </button>
      </div>
    </div>
  );
}
