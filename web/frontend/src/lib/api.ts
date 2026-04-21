import axios from "axios";

const API_BASE = "http://localhost:5001";

export interface QuestionOption {
  url?: string;        // absent until the image is generated
  prompt: string;
  probability?: number;
}

export interface QuestionData {
  question: string;
  options: Record<string, QuestionOption>;
}

export interface ProjectState {
  task: string;
  requirements: RequirementTree;
  image_prompt: string;
  image_url: string;
}

export interface RequirementTree {
  [key: string]: string | number | string[] | RequirementTree;
}

export async function startProject(type: string, prompt: string): Promise<string> {
  const res = await axios.post(`${API_BASE}/api/project`, { type, prompt });
  return res.data.project_id;
}

export async function initProject(projectId: string): Promise<ProjectState> {
  const res = await axios.get(`${API_BASE}/api/project/${projectId}/init`);
  return res.data;
}

export async function getVisualQuestion(projectId: string): Promise<QuestionData> {
  const res = await axios.get(`${API_BASE}/api/project/${projectId}/ask`);
  return res.data;
}

export async function updateRequirements(
  projectId: string,
  answer: string,
): Promise<ProjectState> {
  const res = await axios.post(`${API_BASE}/api/project/${projectId}/update`, { answer });
  return res.data;
}

export async function addRequirement(
  projectId: string,
  requirement: string,
): Promise<ProjectState> {
  const res = await axios.post(`${API_BASE}/api/project/${projectId}/add_requirement`, {
    requirement,
  });
  return res.data;
}

export async function getRequirements(projectId: string): Promise<RequirementTree> {
  const res = await axios.get(`${API_BASE}/api/project/${projectId}/requirements`);
  return res.data.requirements;
}

export async function setRequirements(
  projectId: string,
  requirements: RequirementTree,
): Promise<ProjectState> {
  const res = await axios.put(`${API_BASE}/api/project/${projectId}/requirements`, {
    requirements,
  });
  return res.data;
}

export async function getImagePrompt(projectId: string): Promise<string> {
  const res = await axios.get(`${API_BASE}/api/project/${projectId}/prompt`);
  return res.data.image_prompt;
}

export async function setImagePrompt(
  projectId: string,
  imagePrompt: string,
  regenerate = true,
): Promise<{ image_prompt: string; image_url?: string }> {
  const res = await axios.put(`${API_BASE}/api/project/${projectId}/prompt`, {
    image_prompt: imagePrompt,
    regenerate,
  });
  return res.data;
}

export async function generateImage(projectId: string): Promise<string> {
  const res = await axios.get(`${API_BASE}/api/project/${projectId}/generate_image`);
  return res.data.image_url;
}

export async function changeImageModel(projectId: string, model: string): Promise<void> {
  await axios.post(`${API_BASE}/api/project/${projectId}/change_img_model`, { model });
}

export async function changeRandomSeed(projectId: string): Promise<void> {
  await axios.post(`${API_BASE}/api/project/${projectId}/change_seed`);
}

// ---------------------------------------------------------------------------
// Streaming question endpoint (SSE)
// ---------------------------------------------------------------------------

interface StreamCallbacks {
  onQuestion: (data: QuestionData) => void;
  onImage: (option: string, url: string) => void;
  onDone: () => void;
  onError?: (message: string) => void;
}

/** Opens an SSE stream for the next visual question.
 *  Returns a cleanup function that closes the stream. */
export function streamVisualQuestion(
  projectId: string,
  callbacks: StreamCallbacks,
): () => void {
  const es = new EventSource(`${API_BASE}/api/project/${projectId}/ask/stream`);

  es.onmessage = (event) => {
    const data = JSON.parse(event.data as string);
    if (data.type === "question") {
      const { type: _, ...rest } = data;
      callbacks.onQuestion(rest as QuestionData);
    } else if (data.type === "image") {
      callbacks.onImage(data.option as string, data.url as string);
    } else if (data.type === "done") {
      es.close();
      callbacks.onDone();
    } else if (data.type === "error") {
      es.close();
      callbacks.onError?.(data.message as string);
    }
  };

  es.onerror = () => {
    es.close();
    callbacks.onError?.("Stream connection error");
  };

  return () => es.close();
}
