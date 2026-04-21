"""Flask REST API server for the APE web demo.

Run from the repository root:
    python web/server.py
"""
import json
import os
import sys
import uuid

import numpy as np
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

# Allow importing the `ape` package from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ape import Project

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000"])

_projects: dict[str, Project] = {}

# Map frontend model labels to (provider, model_version)
_MODEL_MAP: dict[str, tuple[str, str]] = {
    "FLUX[schnell]": ("fal", "fal-ai/flux/schnell"),
    "FLUX[dev]":     ("fal", "fal-ai/flux/dev"),
    "FLUX[pro]":     ("fal", "fal-ai/flux-pro/v1.1"),
    "HiDream[fast]": ("fal", "fal-ai/hidream-i1-fast"),
    "HiDream[dev]":  ("fal", "fal-ai/hidream-i1-dev"),
    "DALL-E":        ("openai", "dall-e-3"),
}


def _to_native(obj):
    """Recursively convert numpy scalars to native Python types for JSON."""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def _get_project(project_id: str):
    project = _projects.get(project_id)
    if project is None:
        return None, jsonify({"error": "Project not found"}), 404
    return project, None, None


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------

@app.post("/api/project")
def create_project():
    data = request.get_json()
    task = data.get("type", "Design")
    description = data.get("prompt", "")
    project_id = str(uuid.uuid4())
    _projects[project_id] = Project(
        task=task,
        description=description,
        id=project_id,
        questioner="APE",
        verbose=True,
    )
    return jsonify({"project_id": project_id})


@app.get("/api/project/<project_id>/init")
def init_project(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    return jsonify({
        "task": project.task,
        "requirements": project.requirements,
        "image_prompt": project.image_prompt,
        "image_url": project.img_url,
    })


# ---------------------------------------------------------------------------
# Question / answer
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/api/project/<project_id>/ask/stream")
def ask_question_stream(project_id: str):
    """SSE endpoint: streams question text first, then image URLs as they complete."""
    project, err, code = _get_project(project_id)
    if err:
        return err, code

    @stream_with_context
    def generate():
        try:
            question_json = project.ask_visual_question_text()
            question_json = project.finalize_visual_question(question_json)
            yield _sse(_to_native({"type": "question", **question_json}))
            for opt, url in project.fetch_visual_question_images(question_json):
                yield _sse({"type": "image", "option": opt, "url": url})
            yield _sse({"type": "done"})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/project/<project_id>/update")
def update_requirements(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    data = request.get_json()
    answer = data.get("answer", "")
    project.record_answer(answer)
    project.extract_requirements(answer=answer)
    return jsonify({
        "requirements": project.requirements,
        "image_prompt": project.image_prompt,
        "image_url": project.img_url,
    })


# ---------------------------------------------------------------------------
# Requirements CRUD
# ---------------------------------------------------------------------------

@app.post("/api/project/<project_id>/add_requirement")
def add_requirement(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    user_input = (request.get_json() or {}).get("requirement", "")
    project.add_requirement(user_input)
    return jsonify({
        "requirements": project.requirements,
        "image_prompt": project.image_prompt,
        "image_url": project.img_url,
    })


@app.get("/api/project/<project_id>/requirements")
def get_requirements(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    return jsonify({"requirements": project.requirements})


@app.put("/api/project/<project_id>/requirements")
def set_requirements(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    new_reqs = (request.get_json(silent=True) or {}).get("requirements")
    if not isinstance(new_reqs, dict):
        return jsonify({"error": "`requirements` must be a JSON object"}), 400
    project.set_requirements(new_reqs)
    return jsonify({
        "requirements": project.requirements,
        "image_prompt": project.image_prompt,
        "image_url": project.img_url,
    })


# ---------------------------------------------------------------------------
# Image prompt
# ---------------------------------------------------------------------------

@app.get("/api/project/<project_id>/prompt")
def get_prompt(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    return jsonify({"image_prompt": project.image_prompt})


@app.put("/api/project/<project_id>/prompt")
def set_prompt(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    new_prompt = data.get("image_prompt", "")
    regenerate = bool(data.get("regenerate", True))
    if not isinstance(new_prompt, str) or not new_prompt.strip():
        return jsonify({"error": "`image_prompt` must be a non-empty string"}), 400
    project.set_image_prompt(new_prompt, regenerate=regenerate)
    return jsonify({
        "image_prompt": project.image_prompt,
        "image_url": project.img_url,
    })


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

@app.get("/api/project/<project_id>/generate_image")
def generate_image(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    image_url = project.generate_image()
    return jsonify({"image_url": image_url})


@app.post("/api/project/<project_id>/change_img_model")
def change_image_model(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    label = (request.get_json() or {}).get("model", "")
    entry = _MODEL_MAP.get(label)
    if entry is None:
        return jsonify({"error": f"Unknown model '{label}'"}), 400
    provider, model_version = entry
    project.change_image_model(provider=provider, model_version=model_version)
    return jsonify({"message": "Image model changed successfully"})


@app.post("/api/project/<project_id>/change_seed")
def change_seed(project_id: str):
    project, err, code = _get_project(project_id)
    if err:
        return err, code
    project.seed = int(np.random.randint(0, 10000))
    return jsonify({"message": "Random seed changed successfully"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True, threaded=True)
