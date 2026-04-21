"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import Spinner from "@/components/Spinner";
import {
  initProject,
  streamVisualQuestion,
  updateRequirements,
  addRequirement,
  setRequirements,
  getImagePrompt,
  setImagePrompt,
  generateImage,
  changeImageModel,
  changeRandomSeed,
} from "@/lib/api";
import type { QuestionData, ProjectState, RequirementTree } from "@/lib/api";
import RequirementList from "@/components/RequirementList";
import AdaptiveInput from "@/components/AdaptiveInput";
import "./project.css";

const MODEL_LABELS = [
  "FLUX[schnell]",
  "FLUX[dev]",
  "FLUX[pro]",
  "HiDream[fast]",
  "HiDream[dev]",
  "DALL-E",
];

export default function ProjectClient({ projectId }: { projectId: string }) {
  const [task, setTask] = useState("");
  const [requirements, setRequirementsState] = useState<RequirementTree>({});
  const [draftRequirements, setDraftRequirements] = useState<RequirementTree>({});
  const [imagePrompt, setImagePromptState] = useState("");
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [question, setQuestion] = useState<QuestionData | null>(null);
  const [otherInput, setOtherInput] = useState("");
  const [addInput, setAddInput] = useState("");
  const [selectedModel, setSelectedModel] = useState("FLUX[schnell]");
  const [forceExpanded, setForceExpanded] = useState<boolean | undefined>(undefined);
  const [editingRequirements, setEditingRequirements] = useState(false);

  const [loadingInit, setLoadingInit] = useState(true);
  const [loadingQuestion, setLoadingQuestion] = useState(false);
  const [loadingUpdate, setLoadingUpdate] = useState(false);
  const [loadingImage, setLoadingImage] = useState(false);
  const [loadingPrompt, setLoadingPrompt] = useState(false);

  const initialized = useRef(false);
  const questionStreamRef = useRef<(() => void) | null>(null);

  const applyState = (state: Partial<ProjectState>) => {
    if (state.requirements !== undefined) {
      setRequirementsState(state.requirements);
      setDraftRequirements(state.requirements);
    }
    if (state.image_prompt !== undefined) setImagePromptState(state.image_prompt);
    if (state.image_url !== undefined) setImageUrl(state.image_url);
  };

  const fetchQuestion = useCallback(() => {
    // Close any in-progress stream before starting a new one
    questionStreamRef.current?.();
    setLoadingQuestion(true);
    setQuestion(null);
    setOtherInput("");

    questionStreamRef.current = streamVisualQuestion(projectId, {
      onQuestion: (data) => {
        setQuestion(data);
        setLoadingQuestion(false); // text is ready; images still arriving
      },
      onImage: (option, url) => {
        setQuestion((prev) =>
          prev
            ? { ...prev, options: { ...prev.options, [option]: { ...prev.options[option], url } } }
            : prev,
        );
      },
      onDone: () => { questionStreamRef.current = null; },
      onError: (err) => {
        console.error("Question stream error:", err);
        setLoadingQuestion(false);
        questionStreamRef.current = null;
      },
    });
  }, [projectId]);

  // Cleanup stream on unmount
  useEffect(() => () => { questionStreamRef.current?.(); }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    (async () => {
      try {
        const state = await initProject(projectId);
        setTask(state.task);
        applyState(state);
      } catch (err) {
        console.error("Failed to init project", err);
      } finally {
        setLoadingInit(false); // show the page; question loads independently below
        fetchQuestion();
      }
    })();
  }, [fetchQuestion, projectId]);

  // Answer a question option
  const handleAnswer = useCallback(async (answer: string) => {
    const trimmed = answer.trim();
    if (!trimmed || !question) return;
    setLoadingUpdate(true);
    setLoadingPrompt(true);
    setLoadingImage(true);
    try {
      const state = await updateRequirements(projectId, trimmed);
      applyState(state);
    } catch (err) {
      console.error("Failed to update requirements", err);
    } finally {
      setLoadingUpdate(false);
      setLoadingPrompt(false);
      setLoadingImage(false);
    }
    fetchQuestion();
  }, [fetchQuestion, projectId, question]);

  // Submit edited requirements
  const handleSubmitRequirements = useCallback(async () => {
    setEditingRequirements(false);
    setLoadingPrompt(true);
    setLoadingImage(true);
    try {
      const state = await setRequirements(projectId, draftRequirements);
      applyState(state);
    } catch (err) {
      console.error("Failed to set requirements", err);
    } finally {
      setLoadingPrompt(false);
      setLoadingImage(false);
    }
    fetchQuestion();
  }, [draftRequirements, fetchQuestion, projectId]);

  // Add a free-text requirement
  const handleAddRequirement = useCallback(async () => {
    const trimmed = addInput.trim();
    if (!trimmed) return;
    setLoadingUpdate(true);
    setLoadingPrompt(true);
    setLoadingImage(true);
    try {
      const state = await addRequirement(projectId, trimmed);
      setAddInput("");
      applyState(state);
    } catch (err) {
      console.error("Failed to add requirement", err);
    } finally {
      setLoadingUpdate(false);
      setLoadingPrompt(false);
      setLoadingImage(false);
    }
    fetchQuestion();
  }, [addInput, fetchQuestion, projectId]);

  // Regenerate image with a new random seed
  const handleRegenerate = useCallback(async () => {
    setLoadingImage(true);
    try {
      await changeRandomSeed(projectId);
      const url = await generateImage(projectId);
      setImageUrl(url);
    } catch (err) {
      console.error("Failed to regenerate image", err);
    } finally {
      setLoadingImage(false);
    }
  }, [projectId]);

  // Change image model
  const handleModelChange = useCallback(async (label: string) => {
    setSelectedModel(label);
    setLoadingPrompt(true);
    setLoadingImage(true);
    try {
      await changeImageModel(projectId, label);
      const prompt = await getImagePrompt(projectId);
      setImagePromptState(prompt);
      const url = await generateImage(projectId);
      setImageUrl(url);
    } catch (err) {
      console.error("Failed to change model", err);
    } finally {
      setLoadingPrompt(false);
      setLoadingImage(false);
    }
  }, [projectId]);

  // Save / download current image
  const handleDownload = useCallback(async () => {
    if (!imageUrl) return;
    const blob = await (await fetch(imageUrl)).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ape_result_${projectId}.png`;
    a.click();
  }, [imageUrl, projectId]);

  // Render bold markdown in question text
  const renderQuestion = (text: string) =>
    text.split(/(\*\*.*?\*\*)/).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        part
      ),
    );

  const busy = loadingUpdate || loadingImage || loadingPrompt;

  if (loadingInit) {
    return (
      <div className="loading-page">
        <Spinner size={40} />
        <p>Initialising project…</p>
      </div>
    );
  }

  return (
    <div className="project-page">
      <h1 className="project-title">{task}</h1>

      <div className="project-grid">
        {/* Requirements */}
        <section className="section section-req">
          <div>
            <div className="section-heading-wrapper">
              <div className="section-heading-left">
                <h2 className="section-title">Requirements</h2>
                <div className="expand-collapse-controls">
                  <button
                    className="function-button small"
                    onClick={() => setForceExpanded(true)}
                  >
                    Expand All
                  </button>
                  <button
                    className="function-button small"
                    onClick={() => setForceExpanded(false)}
                  >
                    Collapse All
                  </button>
                </div>
              </div>

              <div className="section-heading-right">
                {editingRequirements ? (
                  <button
                    className="function-button"
                    onClick={handleSubmitRequirements}
                    disabled={busy}
                  >
                    Submit
                  </button>
                ) : (
                  <button
                    className="function-button"
                    onClick={() => setEditingRequirements(true)}
                    disabled={busy}
                  >
                    Edit
                  </button>
                )}
              </div>
            </div>
            <RequirementList
              data={draftRequirements}
              editable={editingRequirements}
              forceExpanded={forceExpanded}
              onChange={setDraftRequirements}
            />
          </div>
          {loadingUpdate && (
            <div className="loading-spinner-wrapper">
              <Spinner size={20} variant="bar" />
            </div>
          )}
          <div className="add-input-row">
            <input
              className="add-input"
              placeholder="Add a requirement…"
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleAddRequirement(); }}
            />
            <button
              className="function-button add-done-button"
              onClick={handleAddRequirement}
              disabled={!addInput.trim() || busy}
            >
              Done
            </button>
          </div>
        </section>

        {/* Image + Prompt */}
        <div className="section-result">
          <section className="section section-image">
            <div className="section-heading-wrapper">
              <h2 className="section-title">Generated Image</h2>
              <button
                className="function-button"
                onClick={handleRegenerate}
                disabled={loadingImage}
              >
                {loadingImage ? "Generating…" : "Regenerate"}
              </button>
            </div>
            {loadingImage ? (
              <div className="loading-spinner-wrapper">
                <Spinner size={32} />
              </div>
            ) : (
              imageUrl && (
                <div className="result-image-wrapper">
                  <Image
                    src={imageUrl}
                    alt="Generated"
                    width={512}
                    height={512}
                    className="result-image"
                  />
                </div>
              )
            )}
            <div className="save-controls">
              {imageUrl && !loadingImage && (
                <button className="save-button" onClick={handleDownload}>
                  Download
                </button>
              )}
            </div>
          </section>

          <section className="section section-prompt">
            <div className="section-heading-wrapper">
              <h2 className="section-title">Prompt</h2>
              <div className="prompt-controls">
                <div className="model-row">
                  <label className="model-label">Model:</label>
                  <select
                    className="model-select"
                    value={selectedModel}
                    onChange={(e) => handleModelChange(e.target.value)}
                  >
                    {MODEL_LABELS.map((l) => (
                      <option key={l} value={l}>{l}</option>
                    ))}
                  </select>
                </div>

                <button
                  className="function-button"
                  onClick={async () => {
                    if (!editingPrompt) {
                      setDraftPrompt(imagePrompt ?? "");
                      setEditingPrompt(true);
                    } else {
                      setLoadingPrompt(true);
                      try {
                        const res = await setImagePrompt(projectId, draftPrompt, true);
                        setImagePromptState(res.image_prompt ?? draftPrompt);
                        if (res.image_url) setImageUrl(res.image_url);
                      } catch (err) {
                        console.error("Failed to save prompt", err);
                      } finally {
                        setLoadingPrompt(false);
                        setEditingPrompt(false);
                      }
                    }
                  }}
                >
                  {editingPrompt ? "Done" : "Edit"}
                </button>
                
              </div>
            </div>
            {loadingPrompt ? (
              <div className="loading-spinner-wrapper">
                <Spinner size={24} />
              </div>
            ) : editingPrompt ? (
              <textarea
                className="prompt-textarea"
                value={draftPrompt}
                onChange={(e) => setDraftPrompt(e.target.value)}
              />
            ) : (
              <p className="prompt-text">{imagePrompt}</p>
            )}
          </section>
        </div>

        {/* Question */}
        <section className="section section-question">
          <div className="section-heading-wrapper">
            <h2 className="section-title">Question</h2>
          </div>
          {loadingQuestion ? (
            <div className="loading-spinner-wrapper">
              <Spinner size={30} />
            </div>
          ) : question ? (
            <div>
              <p className="question-text">{renderQuestion(question.question)}</p>
              <div className="options-grid">
                {Object.entries(question.options).map(([label, option]) => (
                  <button
                    key={label}
                    className="option-button"
                    onClick={() => handleAnswer(label)}
                    disabled={busy}
                  >
                    {option.url ? (
                      <Image
                        src={option.url}
                        alt={label}
                        width={256}
                        height={256}
                        className="option-image"
                      />
                    ) : (
                      <div className="option-image-skeleton" />
                    )}
                    <p className="option-label">{label}</p>
                  </button>
                ))}
              </div>
              <div className="other-input-row">
                <label>Other:</label>
                <AdaptiveInput
                  className="other-input"
                  placeholder="please specify…"
                  value={otherInput}
                  onChange={setOtherInput}
                  onEnter={() => handleAnswer(otherInput)}
                  minCh={4}
                />
              </div>
            </div>
          ) : (
            <p className="question-text muted">No question yet — click &quot;New Query&quot;.</p>
          )}
        </section>
      </div>
    </div>
  );
}
