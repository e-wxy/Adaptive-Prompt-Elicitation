# Web Demo

A prototype web demo for Adaptive Prompt Elicitation (APE), built with a Python/Flask backend and a Next.js frontend.

## Setup

### 1. Backend

Install dependencies (from the repo root):

```bash
pip install -r web/requirements.txt
```

Ensure your `.env` file in the repo root contains the required API keys (`OPENAI_KEY`, `FAL_KEY`).

### 2. Frontend

```bash
cd web/frontend
npm install
```

## Running

Open two terminals from the **repo root**:

**Terminal 1 — backend:**
```bash
python web/server.py
```

**Terminal 2 — frontend:**
```bash
cd web/frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Usage

1. **Home page**: enter a design type and a short description of your idea, then click **START**.
2. **Project page**:
   - Click an image option to answer. Requirements and the generated image update automatically.
   - Use **"Other"** to type a free-form answer.
   - Use the **Requirements** panel to refine constraints manually; click **Edit** to enable direct editing, or type in  "Add a requirement ..." to suggest additional constraints or changes.
   - Use the **Prompt** panel to view or edit the image prompt.
   - Click **Regenerate** to create a new image variation with a different random seed.
   - Change the **Model** dropdown to switch image generation backends at any time.
   - Click **Download** to save the current image locally.
