"use client";
import { useEffect, useRef, useState } from "react";

interface ComboboxProps {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  inputClassName?: string;
}

export default function Combobox({
  value,
  options,
  onChange,
  placeholder,
  className,
  inputClassName,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (opt: string) => {
    onChange(opt); // empty string clears input for free-text entry
    setOpen(false);
  };

  return (
    <div ref={containerRef} className={`combobox-wrapper ${className ?? ""}`}>
      <div className="combobox-input-row">
        <input
          type="text"
          className={`combobox-input ${inputClassName ?? ""}`}
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
        <button
          type="button"
          className="combobox-arrow"
          tabIndex={-1}
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle options"
        >
          ▾
        </button>
      </div>

      {open && (
        <ul className="combobox-list" role="listbox">
          {options.map((opt) => (
            <li
              key={opt}
              role="option"
              aria-selected={opt === value}
              className={`combobox-item ${opt === value ? "selected" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); handleSelect(opt); }}
            >
              {opt}
            </li>
          ))}
          {/* Blank trailing item — select to clear and type a custom value */}
          <li
            role="option"
            aria-selected={false}
            className="combobox-item combobox-item-custom"
            onMouseDown={(e) => { e.preventDefault(); handleSelect(""); }}
          >
            <span className="combobox-custom-hint">Custom…</span>
          </li>
        </ul>
      )}
    </div>
  );
}
