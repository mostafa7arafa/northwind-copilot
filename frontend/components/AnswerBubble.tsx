"use client";

import { Fragment, type ReactNode } from "react";

/** Render `**bold**` spans inline; everything else is plain text. */
function renderInline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    )
  );
}

/**
 * Split a prose block into display lines. Models frequently emit an inline
 * ranked list ("… are: 1. A $10 2. B $9 3. C $8") with no newlines, which
 * otherwise renders as one run-on wall. Break before a ` N. Word` boundary
 * (small integer, then a capitalised item) while leaving decimals like
 * "$839,491.63" and years like "2017." untouched.
 */
function toLines(text: string): string[] {
  return text
    .replace(/\s+(?=(?:[1-9]|1\d)\.\s+[A-Z"'])/g, "\n")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

/**
 * The assistant's reply as one clean chat bubble: the prose answer, with the
 * short insight bullets folded in below a hairline (same bubble — not a second
 * card). Deliberately unadorned so a turn reads as a single message.
 */
export function AnswerBubble({
  text,
  bullets,
  tint,
}: {
  text: string;
  bullets: string[];
  tint: string;
}) {
  const lines = text ? toLines(text) : [];

  return (
    <div
      className="rounded-[var(--radius-card)] border border-hairline bg-surface px-4 py-3"
      style={{ borderLeft: `2px solid ${tint}` }}
    >
      {lines.length > 0 && (
        <div className="space-y-1.5 text-[14px] leading-relaxed text-ink/90">
          {lines.map((line, i) => (
            <p key={i}>{renderInline(line)}</p>
          ))}
        </div>
      )}
      {bullets.length > 0 && (
        <ul className="mt-2.5 space-y-1 border-t border-hairline/60 pt-2.5">
          {bullets.map((b, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-ink/65">
              <span
                className="mt-[7px] h-1 w-1 shrink-0 rounded-full"
                style={{ background: tint }}
              />
              <span>{renderInline(b)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
