"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { startProject } from "@/lib/api";
import Combobox from "@/components/Combobox";
import "./home.css";

const DESIGN_TYPES = [
  "Interior Design",
  "Poster Design",
  "Logo Design",
  "Architectural Style",
  "Landscape Design",
  "Postcard Design",
  "Photography",
  "Painting",
];

const EXAMPLES: { type: string; description: string }[] = [
  { type: "Interior Design",    description: "A modern study room with a large window" },
  { type: "Poster Design",      description: "A flat-design travel poster for Paris" },
  { type: "Photography",        description: "A photo of Finnish winter" },
];

export default function HomePage() {
  const router = useRouter();
  const [designType, setDesignType] = useState(DESIGN_TYPES[0]);
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);

  const handleStart = async () => {
    if (!description.trim()) return;
    setLoading(true);
    try {
      const projectId = await startProject(designType, description);
      router.push(`/project/${projectId}`);
    } catch (err) {
      console.error("Failed to start project", err);
      setLoading(false);
    }
  };

  return (
    <div className="home-container">
      <div className="home-content">
        <h1 className="home-title">What image would you like to create?</h1>

        <form
          className="home-form"
          onSubmit={(e) => { e.preventDefault(); handleStart(); }}
        >
          <div className="type-row">
            <label className="type-label">Design type:</label>
            <Combobox
              value={designType}
              options={DESIGN_TYPES}
              onChange={setDesignType}
              placeholder="e.g. Interior Design"
            />
          </div>

          <textarea
            className="home-input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe your idea..."
            disabled={loading}
          />

          <button type="submit" className="start-button" disabled={loading || !description.trim()}>
            {loading ? "Starting..." : "START"}
          </button>
        </form>

        <div className="examples">
          <p className="examples-label">Try an example:</p>
          <div className="examples-row">
            {EXAMPLES.map((ex) => (
              <button
                key={ex.description}
                className="example-chip"
                onClick={() => { setDesignType(ex.type); setDescription(ex.description); }}
              >
                {ex.description}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
