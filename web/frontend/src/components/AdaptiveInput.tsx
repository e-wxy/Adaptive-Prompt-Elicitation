"use client";
import React, { useEffect, useRef } from "react";

interface AdaptiveInputProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
  minCh?: number;
  onEnter?: () => void;
}

const AdaptiveInput: React.FC<AdaptiveInputProps> = ({
  value,
  onChange,
  className,
  placeholder,
  minCh = 2,
  onEnter,
}) => {
  const divRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    if ((el.textContent ?? "") !== (value ?? "")) {
      el.textContent = value ?? "";
    }
  }, [value]);

  return (
    <div
      ref={divRef}
      className={className}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="false"
      data-placeholder={placeholder ?? ""}
      onInput={(e) => onChange((e.currentTarget.textContent ?? "").replace(/\s+$/g, ""))}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          onEnter?.();
        }
      }}
      onPaste={(e) => {
        e.preventDefault();
        const text = e.clipboardData.getData("text/plain").replace(/\n/g, " ");
        document.execCommand("insertText", false, text);
      }}
      style={{
        display: "inline-block",
        width: "max-content",
        maxWidth: "100%",
        minWidth: `${Math.max(1, minCh)}ch`,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflowWrap: "anywhere",
      }}
    />
  );
};

export default AdaptiveInput;
