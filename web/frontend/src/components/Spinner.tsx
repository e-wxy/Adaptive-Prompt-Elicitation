import React from "react";

interface SpinnerProps {
  size?: number;
  variant?: "ring" | "bar";
}

const Spinner: React.FC<SpinnerProps> = ({ size = 24, variant = "ring" }) => {
  if (variant === "bar") {
    return (
      <div
        style={{ width: size * 4, height: 4 }}
        className="spinner-bar"
        aria-label="Loading"
      />
    );
  }
  return (
    <div
      style={{ width: size, height: size }}
      className="spinner-ring"
      aria-label="Loading"
    />
  );
};

export default Spinner;
