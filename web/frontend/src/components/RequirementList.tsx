"use client";
import React, { useState } from "react";
import AdaptiveInput from "./AdaptiveInput";
import type { RequirementTree } from "@/lib/api";

type RequirementValue = string | number | string[] | RequirementTree;

interface RequirementListProps {
  data: RequirementTree;
  level?: number;
  editable?: boolean;
  forceExpanded?: boolean;
  onChange: (next: RequirementTree) => void;
}

const RequirementList: React.FC<RequirementListProps> = ({
  data,
  level = 0,
  editable = false,
  forceExpanded,
  onChange,
}) => (
  <ul className={`requirement-list level-${level}`}>
    {Object.entries(data).map(([key, value]) => (
      <RequirementItem
        key={key}
        label={key}
        value={value}
        level={level}
        editable={editable}
        forceExpanded={forceExpanded}
        onChange={(updated) => onChange({ ...data, [key]: updated })}
      />
    ))}
  </ul>
);

const RequirementItem: React.FC<{
  label: string;
  value: RequirementValue;
  level: number;
  editable?: boolean;
  forceExpanded?: boolean;
  onChange: (value: RequirementValue) => void;
}> = ({ label, value, level, editable = false, forceExpanded, onChange }) => {
  const [localExpanded, setLocalExpanded] = useState(true);
  const isExpanded = forceExpanded !== undefined ? forceExpanded : localExpanded;

  const isStringArray =
    Array.isArray(value) && value.every((v) => typeof v === "string");
  const isNested =
    value !== null &&
    typeof value === "object" &&
    !isStringArray &&
    !Array.isArray(value);

  return (
    <li className="requirement-entry">
      <div className="requirement-row">
        <button
          className="toggle-button"
          onClick={() => isNested && setLocalExpanded((p) => !p)}
        >
          {isNested ? (isExpanded ? "−" : "+") : "*"}
        </button>
        <span className="requirement-label">{label}:</span>

        {!isNested && !isStringArray && editable && (
          <AdaptiveInput
            className="requirement-value"
            value={String(value ?? "")}
            onChange={(raw) => {
              if (raw === "") { onChange(""); return; }
              const num = Number(raw);
              onChange(!Number.isNaN(num) && /^-?\d*(\.\d+)?$/.test(raw) ? num : raw);
            }}
            minCh={2}
          />
        )}
        {!isNested && !isStringArray && !editable && (
          <span className="requirement-value">{String(value ?? "")}</span>
        )}
        {!isNested && isStringArray && editable && (
          <AdaptiveInput
            className="requirement-value"
            value={(value as string[]).join(", ")}
            onChange={(raw) =>
              onChange(raw.split(",").map((s) => s.trim()).filter(Boolean))
            }
            placeholder="comma separated"
            minCh={2}
          />
        )}
        {!isNested && isStringArray && !editable && (
          <span className="requirement-value">{(value as string[]).join(", ")}</span>
        )}
      </div>

      {isNested && isExpanded && (
        <RequirementList
          data={value as RequirementTree}
          level={level + 1}
          editable={editable}
          forceExpanded={forceExpanded}
          onChange={(child) => onChange(child)}
        />
      )}
    </li>
  );
};

export default RequirementList;
