"use client";

import { Check, Copy, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

/**
 * A full-viewport overlay rendered through a portal to `document.body`.
 *
 * Rendering via a portal is essential here: the cards live inside framer-motion
 * wrappers that apply a CSS `transform`, and a `position: fixed` child of a
 * transformed ancestor is positioned relative to that ancestor — not the
 * viewport — which traps and clips a naive fullscreen overlay. Escaping to
 * `document.body` fixes positioning; Escape and backdrop-click both close it.
 */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex flex-col bg-bg/95 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="eyebrow">{title}</div>
        <button
          type="button"
          onClick={onClose}
          title="Close (Esc)"
          className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <X size={18} />
        </button>
      </div>
      <div className="min-h-0 flex-1" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>,
    document.body
  );
}

/** A layered card surface with a hairline border and header slot. */
export function Panel({
  title,
  eyebrow,
  actions,
  children,
  className,
}: {
  title?: React.ReactNode;
  eyebrow?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "card-lift overflow-hidden rounded-[var(--radius-card)] border border-hairline bg-surface",
        className
      )}
    >
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-hairline px-4 py-2.5">
          <div className="flex items-baseline gap-2.5">
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            {title && <span className="text-[13px] text-ink">{title}</span>}
          </div>
          {actions && <div className="flex items-center gap-1">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/** A quiet icon button used in card toolbars. */
export function GhostButton({
  onClick,
  title,
  children,
  active,
}: {
  onClick?: () => void;
  title: string;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-electric/60",
        active && "bg-surface-2 text-ink"
      )}
    >
      {children}
    </button>
  );
}

/** Copy-to-clipboard button that morphs into a check on success. */
export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <GhostButton
      title={copied ? "Copied" : "Copy"}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      }}
    >
      {copied ? (
        <Check size={13} className="text-ok" />
      ) : (
        <Copy size={13} />
      )}
      {copied ? "Copied" : "Copy"}
    </GhostButton>
  );
}
