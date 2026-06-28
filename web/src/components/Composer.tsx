import { useState, useRef, useCallback, type KeyboardEvent } from 'react';

interface ComposerProps {
  disabled: boolean;
  onSend: (message: string) => void;
  variant?: 'default' | 'landing';
}

export function Composer({ disabled, onSend, variant = 'default' }: ComposerProps) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
  );
}
