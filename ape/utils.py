"""Utility functions and unified API wrappers for LLM and image generation."""
import base64
import imghdr
import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import json_repair
import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image

import fal_client
from anthropic import Anthropic
from openai import OpenAI

# Optional providers
try:
    from google import genai as google_genai
    from google.genai import types as google_types
    GOOGLE_GENAI_AVAILABLE = True
except Exception:
    GOOGLE_GENAI_AVAILABLE = False

try:
    from vertexai.preview.generative_models import GenerativeModel, Part
    import vertexai
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False

load_dotenv()

# ===== MODEL REGISTRY =====

MODELS = {
    # https://platform.openai.com/docs/models
    "openai": {
        "text": ["gpt-5", "gpt-5-mini", "gpt-5-nano",
                 "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
                 "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "vision": ["gpt-5", "gpt-5-mini", "gpt-5-nano",
                   "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
                   "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "image": ["dall-e-3", "dall-e-2", "gpt-image-1"],
    },
    # https://docs.anthropic.com/en/docs/about-claude/models/overview
    "anthropic": {
        "text": ["claude-opus-4-7", "claude-sonnet-4-6",
                 "claude-opus-4-1-20250805", "claude-sonnet-4-20250514",
                 "claude-haiku-4-5-20251001",
                 "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022"],
        "vision": ["claude-opus-4-7", "claude-sonnet-4-6",
                   "claude-opus-4-1-20250805", "claude-sonnet-4-20250514",
                   "claude-haiku-4-5-20251001",
                   "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022"],
        "image": [],
    },
    # https://cloud.google.com/vertex-ai/generative-ai/docs/models
    "vertex": {
        "text": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                 "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "vision": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                   "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "image": ["imagen-4.0-generate-001", "imagen-4.0-fast-generate-001"],
    },
    "fal": {
        "image": ["fal-ai/flux/schnell", "fal-ai/flux/dev",
                  "fal-ai/flux-pro/v1.1", "fal-ai/flux-pro/v1.1-ultra",
                  "fal-ai/hidream-i1-fast", "fal-ai/hidream-i1-dev",
                  "fal-ai/recraft-v3"],
    },
    # https://googleapis.github.io/python-genai/
    "google": {
        "text": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                 "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "vision": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                   "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "image": ["gemini-2.5-flash-image-preview",
                  "imagen-4.0-generate-001", "imagen-4.0-fast-generate-001"],
    },
}

DEFAULT_MODELS = {
    "openai":    {"text": "gpt-4.1-mini",           "vision": "gpt-4.1-mini",          "image": "dall-e-3"},
    "anthropic": {"text": "claude-sonnet-4-20250514","vision": "claude-sonnet-4-20250514"},
    "vertex":    {"text": "gemini-2.0-flash-lite",  "vision": "gemini-2.0-flash-lite",  "image": "imagen-4.0-fast-generate-001"},
    "fal":       {"image": "fal-ai/flux/schnell"},
    "google":    {"text": "gemini-2.0-flash-lite",  "vision": "gemini-2.0-flash-lite",  "image": "imagen-4.0-fast-generate-001"},
}


# ===== UTILITY FUNCTIONS =====

def parse_llm_output_to_json(model_output: str) -> Any:
    """Parse LLM output string into a JSON object, stripping markdown fences if present."""
    if "```" in model_output:
        model_output = model_output.split("```")[1].strip()
    if model_output[:4].lower() == "json":
        model_output = model_output[4:].strip()
    model_output = re.sub(r",(\s*[}\]])", r"\1", model_output)
    try:
        return json_repair.loads(model_output)
    except ValueError as exc:
        raise ValueError("Error parsing LLM JSON output.") from exc


_DEFAULT_PROMPT_FOLDER = Path(__file__).parent / "prompt_templates"


def load_prompt(file_name: str, folder_name: Optional[str] = None) -> str:
    """Load a prompt template from the given folder.

    Args:
        file_name: Template filename (e.g. "query_generation.md").
        folder_name: Directory containing templates. Falls back to the
            PROMPT_FOLDER environment variable, then to the bundled
            ``ape/prompt_templates/`` directory.

    Returns:
        Template content as a string.
    """
    if folder_name is None:
        folder_name = os.getenv("PROMPT_FOLDER") or str(_DEFAULT_PROMPT_FOLDER)
    folder_name = str(folder_name).rstrip("/") + "/"
    file_path = Path(folder_name + file_name)
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt template '{file_name}' not found in '{folder_name}'.")
    return file_path.read_text()


def json_to_html(req_dict: dict) -> str:
    """Recursively convert a nested dict to an HTML unordered list."""
    def _render(d):
        html = "<ul>"
        for key, value in d.items():
            if isinstance(value, dict):
                html += f"<li>{key}{_render(value)}</li>"
            elif isinstance(value, list):
                html += f"<li>{key}<ul>" + "".join(f"<li>{item}</li>" for item in value) + "</ul></li>"
            else:
                html += f"<li>{key}: {value}</li>"
        html += "</ul>"
        return html
    return _render(req_dict)


def download_image(url: str) -> Optional[Image.Image]:
    """Download an image from a URL and return a PIL Image, or None on failure."""
    response = requests.get(url)
    if response.status_code == 200:
        return Image.open(BytesIO(response.content))
    return None


def save_images(urls, save_folder: str = "outputs/images/", file_prefix: str = "image"):
    """Download and save images from a URL or list of URLs to local disk."""
    os.makedirs(save_folder, exist_ok=True)
    if isinstance(urls, str):
        urls = [urls]
    for i, url in enumerate(urls):
        img = download_image(url)
        if img:
            img.save(os.path.join(save_folder, f"{file_prefix}_{i + 1}.png"))


def convert_log_to_json_array(log_file: str, output_file: Optional[str] = None) -> List[dict]:
    """Convert a JSONL log file into a proper JSON array file."""
    if not os.path.exists(log_file):
        raise FileNotFoundError(f"Log file not found: {log_file}")
    if output_file is None:
        output_file = os.path.splitext(log_file)[0] + ".json"

    entries = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json_repair.loads(line))
                except Exception:
                    pass

    with open(output_file, "w") as out:
        json.dump(entries, out, indent=2)
    return entries


# ===== IMAGE UTILITIES =====

def encode_image_base64(image_path: str) -> str:
    """Encode a local image file to a base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_mime_type(image_path: str) -> str:
    """Detect image MIME type from file contents, with extension fallback."""
    detected = imghdr.what(image_path)
    if detected:
        mapping = {"jpeg": "image/jpeg", "png": "image/png",
                   "gif": "image/gif", "webp": "image/webp"}
        if detected in mapping:
            return mapping[detected]
    ext = Path(image_path).suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")


# ===== LLM AGENT =====

class LLMAgent:
    """Unified LLM interface supporting OpenAI, Anthropic, Google, and Vertex AI."""

    def __init__(self, provider: str, api_key: Optional[str] = None,
                 model_version: Optional[str] = None, **kwargs):
        """
        Args:
            provider: One of "openai", "anthropic", "vertex", "google".
            api_key: API key (read from environment variables if omitted).
            model_version: Specific model version; defaults to provider default.
            **kwargs: Provider-specific options (e.g. project_id, location for Vertex/Google).
        """
        self.provider = provider.lower()
        self.kwargs = kwargs

        if self.provider == "openai":
            self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_KEY"))
            self.model_version = model_version or DEFAULT_MODELS["openai"]["text"]

        elif self.provider == "anthropic":
            self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_KEY"))
            self.model_version = model_version or DEFAULT_MODELS["anthropic"]["text"]

        elif self.provider == "vertex":
            if not VERTEX_AVAILABLE:
                raise ImportError("Vertex AI SDK not available. Install google-cloud-aiplatform.")
            project_id = kwargs.get("project_id", os.getenv("VERTEX_PROJECT_ID"))
            location = kwargs.get("location", os.getenv("VERTEX_LOCATION", "us-central1"))
            if not project_id:
                raise ValueError("project_id required for Vertex AI.")
            vertexai.init(project=project_id, location=location)
            self.client = GenerativeModel(model_version or DEFAULT_MODELS["vertex"]["text"])
            self.model_version = model_version or DEFAULT_MODELS["vertex"]["text"]

        elif self.provider == "google":
            if not GOOGLE_GENAI_AVAILABLE:
                raise ImportError("google-genai SDK not available. Install google-genai.")
            project_id = kwargs.get("project_id", os.getenv("VERTEX_PROJECT_ID"))
            location = kwargs.get("location", os.getenv("VERTEX_LOCATION", "us-central1"))
            if not project_id:
                raise ValueError("project_id required for Google Gen AI.")
            self.client = google_genai.Client(project=project_id, location=location)
            self.model_version = model_version or DEFAULT_MODELS["google"]["text"]

        else:
            raise ValueError(f"Unsupported provider: '{provider}'. "
                             f"Choose from: {list(MODELS.keys())}.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_openai_messages(self, prompt: str, system_prompt: Optional[str] = None,
                               image_content: Optional[Dict] = None) -> List[Dict]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if image_content:
            messages.append({"role": "user", "content": [{"type": "text", "text": prompt}, image_content]})
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    def _build_anthropic_messages(self, prompt: str,
                                  image_content: Optional[Dict] = None) -> List[Dict]:
        content = [{"type": "text", "text": prompt}]
        if image_content:
            content.append(image_content)
        return [{"role": "user", "content": content}]

    def _prepare_image_content(self, image_path_or_url: str) -> Any:
        """Encode an image into the provider-specific format."""
        is_url = image_path_or_url.startswith(("http://", "https://"))

        if self.provider == "openai":
            if is_url:
                return {"type": "image_url", "image_url": {"url": image_path_or_url}}
            b64 = encode_image_base64(image_path_or_url)
            mime = get_image_mime_type(image_path_or_url)
            return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

        elif self.provider == "anthropic":
            if is_url:
                return {"type": "image", "source": {"type": "url", "url": image_path_or_url}}
            b64 = encode_image_base64(image_path_or_url)
            mime = get_image_mime_type(image_path_or_url)
            return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}

        elif self.provider == "vertex":
            if is_url:
                resp = requests.get(image_path_or_url)
                if resp.status_code != 200:
                    raise ValueError(f"Failed to download image from {image_path_or_url}.")
                return Part.from_data(resp.content, mime_type="image/jpeg")
            with open(image_path_or_url, "rb") as f:
                data = f.read()
            return Part.from_data(data, mime_type=get_image_mime_type(image_path_or_url))

        elif self.provider == "google":
            if is_url:
                return google_types.Part.from_uri(file_uri=image_path_or_url)
            return Image.open(image_path_or_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, prompt: str, system_prompt: Optional[str] = None,
             temperature: float = 0.7, max_tokens: int = 1024,
             seed: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        """Generate text from a text prompt.

        Returns:
            Dict with keys: "text", "usage", "model", "logprobs".
        """
        if self.provider == "openai":
            messages = self._build_openai_messages(prompt, system_prompt)
            response = self.client.chat.completions.create(
                model=self.model_version, messages=messages,
                temperature=temperature, max_tokens=max_tokens, seed=seed, **kwargs,
            )
            return {
                "text": response.choices[0].message.content,
                "usage": response.usage,
                "model": response.model,
                "logprobs": getattr(response.choices[0], "logprobs", None),
            }

        elif self.provider == "anthropic":
            params = {
                "model": self.model_version,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": self._build_anthropic_messages(prompt),
                **kwargs,
            }
            if system_prompt is not None:
                params["system"] = system_prompt
            response = self.client.messages.create(**params)
            return {
                "text": response.content[0].text,
                "usage": {"input_tokens": response.usage.input_tokens,
                          "output_tokens": response.usage.output_tokens},
                "model": response.model,
                "logprobs": None,
            }

        elif self.provider == "vertex":
            gen_cfg = {"temperature": temperature, "max_output_tokens": max_tokens, **kwargs}
            model = GenerativeModel(self.model_version, system_instruction=system_prompt) \
                if system_prompt else self.client
            response = model.generate_content(prompt, generation_config=gen_cfg)
            usage = response.usage_metadata
            return {
                "text": response.text,
                "usage": {"input_tokens": getattr(usage, "prompt_token_count", None),
                          "output_tokens": getattr(usage, "candidates_token_count", None)},
                "model": self.model_version,
                "logprobs": None,
            }

        elif self.provider == "google":
            gen_cfg = google_types.GenerateContentConfig(
                temperature=temperature, max_output_tokens=max_tokens,
            )
            response = self.client.models.generate_content(
                model=self.model_version, contents=prompt, config=gen_cfg,
            )
            usage = getattr(response, "usage_metadata", None)
            return {
                "text": getattr(response, "text", None),
                "usage": {"input_tokens": getattr(usage, "prompt_token_count", None),
                          "output_tokens": getattr(usage, "response_token_count", None)},
                "model": self.model_version,
                "logprobs": None,
            }

    def call_with_vision(self, prompt: str, image_path_or_url: str,
                         system_prompt: Optional[str] = None,
                         temperature: float = 0.7, max_tokens: int = 1024,
                         seed: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        """Generate text from a combined text and image prompt.

        Returns:
            Dict with keys: "text", "usage", "model", "logprobs".
        """
        if not any(self.model_version.startswith(m)
                   for m in MODELS[self.provider].get("vision", [])):
            raise ValueError(f"Model '{self.model_version}' does not support vision input.")

        image_content = self._prepare_image_content(image_path_or_url)

        if self.provider == "openai":
            messages = self._build_openai_messages(prompt, system_prompt, image_content)
            response = self.client.chat.completions.create(
                model=self.model_version, messages=messages,
                temperature=temperature, max_tokens=max_tokens, seed=seed, **kwargs,
            )
            return {
                "text": response.choices[0].message.content,
                "usage": response.usage,
                "model": response.model,
                "logprobs": getattr(response.choices[0], "logprobs", None),
            }

        elif self.provider == "anthropic":
            params = {
                "model": self.model_version,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": self._build_anthropic_messages(prompt, image_content),
                **kwargs,
            }
            if system_prompt is not None:
                params["system"] = system_prompt
            response = self.client.messages.create(**params)
            return {
                "text": response.content[0].text,
                "usage": {"input_tokens": response.usage.input_tokens,
                          "output_tokens": response.usage.output_tokens},
                "model": response.model,
                "logprobs": None,
            }

        elif self.provider == "vertex":
            gen_cfg = {"temperature": temperature, "max_output_tokens": max_tokens, **kwargs}
            model = GenerativeModel(self.model_version, system_instruction=system_prompt) \
                if system_prompt else self.client
            response = model.generate_content([prompt, image_content], generation_config=gen_cfg)
            usage = response.usage_metadata
            return {
                "text": response.text,
                "usage": {"input_tokens": getattr(usage, "prompt_token_count", None),
                          "output_tokens": getattr(usage, "candidates_token_count", None)},
                "model": self.model_version,
                "logprobs": None,
            }

        elif self.provider == "google":
            gen_cfg = google_types.GenerateContentConfig(
                temperature=temperature, max_output_tokens=max_tokens,
            )
            response = self.client.models.generate_content(
                model=self.model_version, contents=[prompt, image_content], config=gen_cfg,
            )
            usage = getattr(response, "usage_metadata", None)
            return {
                "text": getattr(response, "text", None),
                "usage": {"input_tokens": getattr(usage, "prompt_token_count", None),
                          "output_tokens": getattr(usage, "response_token_count", None)},
                "model": self.model_version,
                "logprobs": None,
            }

    @classmethod
    def list_available_models(cls, provider: str) -> Dict[str, List[str]]:
        """Return available model IDs for a given provider."""
        return MODELS.get(provider.lower(), {})


# ===== IMAGE GENERATOR =====

class ImageGenerator:
    """Unified image generation interface supporting OpenAI (DALL-E), FAL AI, and Vertex/Google."""

    def __init__(self, provider: str, api_key: Optional[str] = None,
                 model_version: Optional[str] = None,
                 save_folder: str = "outputs/images", **kwargs):
        """
        Args:
            provider: One of "openai", "fal", "vertex", "google".
            api_key: API key (read from environment variables if omitted).
            model_version: Specific model version; defaults to provider default.
            save_folder: Local folder for saving generated images (Vertex/Google).
            **kwargs: Provider-specific options.
        """
        self.provider = provider.lower()
        self.save_folder = save_folder
        self.kwargs = kwargs
        os.makedirs(save_folder, exist_ok=True)

        if self.provider == "openai":
            self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_KEY"))
            self.model_version = model_version or DEFAULT_MODELS["openai"]["image"]
            self._fal_sizes = {}
            self._openai_sizes = ["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]

        elif self.provider == "fal":
            fal_client.api_key = api_key or os.getenv("FAL_KEY")
            self.model_version = model_version or DEFAULT_MODELS["fal"]["image"]
            self._fal_sizes = {
                "square_hd": {"width": 1024, "height": 1024},
                "square":    {"width": 512,  "height": 512},
                "large":     {"width": 1024, "height": 1024},
                "small":     {"width": 512,  "height": 512},
                "portrait_4_3":  {"width": 768,  "height": 1024},
                "portrait_16_9": {"width": 576,  "height": 1024},
                "landscape_4_3": {"width": 1024, "height": 768},
                "landscape_16_9":{"width": 1024, "height": 576},
            }

        elif self.provider == "vertex":
            if not VERTEX_AVAILABLE:
                raise ImportError("Vertex AI SDK not available. Install google-cloud-aiplatform.")
            project_id = kwargs.get("project_id", os.getenv("VERTEX_PROJECT_ID"))
            location = kwargs.get("location", os.getenv("VERTEX_LOCATION", "us-central1"))
            if not project_id:
                raise ValueError("project_id required for Vertex AI.")
            vertexai.init(project=project_id, location=location)
            self.model_version = model_version or DEFAULT_MODELS["vertex"]["image"]

        elif self.provider == "google":
            if not GOOGLE_GENAI_AVAILABLE:
                raise ImportError("google-genai SDK not available. Install google-genai.")
            project_id = kwargs.get("project_id", os.getenv("VERTEX_PROJECT_ID"))
            location = kwargs.get("location", os.getenv("VERTEX_LOCATION", "us-central1"))
            if not project_id:
                raise ValueError("project_id required for Google Gen AI.")
            self.client = google_genai.Client(project=project_id, location=location)
            self.model_version = model_version or DEFAULT_MODELS["google"]["image"]

        else:
            raise ValueError(f"Unsupported provider: '{provider}'. "
                             f"Choose from: {list(MODELS.keys())}.")

    def generate_image(self, prompt: str, size: str = "1024x1024",
                       n: int = 1, seed: Optional[int] = None,
                       file_prefix: str = "image", **kwargs) -> Dict[str, Any]:
        """Generate images from a text prompt.

        Args:
            prompt: Text description of the desired image.
            size: Image size — a named size (e.g. "square_hd") or "WxH" string.
            n: Number of images to generate.
            seed: Random seed for reproducibility (FAL only).
            file_prefix: Filename prefix when saving to disk (Vertex/Google).

        Returns:
            Dict with keys "url" (str or list), "seed", and "model".
        """
        if self.provider == "openai":
            if self.model_version == "dall-e-3" and n > 1:
                urls = []
                for _ in range(n):
                    resp = self.client.images.generate(
                        model=self.model_version, prompt=prompt, size=size, n=1, **kwargs
                    )
                    urls.append(resp.data[0].url)
                return {"url": urls, "seed": None, "model": self.model_version}
            response = self.client.images.generate(
                model=self.model_version, prompt=prompt, size=size, n=n, **kwargs
            )
            urls = [img.url for img in response.data]
            return {"url": urls[0] if n == 1 else urls, "seed": None, "model": self.model_version}

        elif self.provider == "fal":
            if isinstance(size, str) and "x" in size:
                w, h = map(int, size.split("x"))
                image_size = {"width": w, "height": h}
            else:
                image_size = self._fal_sizes.get(str(size), self._fal_sizes["square_hd"])
            handler = fal_client.submit(
                self.model_version,
                arguments={"prompt": prompt, "image_size": image_size,
                           "num_images": n, "seed": seed, **kwargs},
            )
            result = handler.get()
            urls = [img["url"] for img in result["images"]]
            return {"url": urls[0] if n == 1 else urls,
                    "seed": result.get("seed"), "model": self.model_version}

        elif self.provider == "vertex":
            from vertexai.preview.vision_models import ImageGenerationModel
            model = ImageGenerationModel.from_pretrained(self.model_version)
            images = model.generate_images(prompt=prompt, number_of_images=n, **kwargs)
            paths = []
            for i, image in enumerate(images):
                path = os.path.join(self.save_folder, f"{file_prefix}_{i + 1}.png")
                image.save(path)
                paths.append(path)
            return {"url": paths[0] if n == 1 else paths, "seed": None, "model": self.model_version}

        elif self.provider == "google":
            if self.model_version.startswith("imagen-"):
                config = google_types.GenerateImagesConfig()
                paths = []
                for i in range(n):
                    resp = self.client.models.generate_images(
                        model=self.model_version, prompt=prompt, config=config,
                    )
                    img_obj = resp.generated_images[0].image
                    path = os.path.join(self.save_folder, f"{file_prefix}_{i + 1}.png")
                    img_obj.save(path)
                    paths.append(path)
                return {"url": paths[0] if n == 1 else paths, "seed": None, "model": self.model_version}
            else:
                gen_cfg = google_types.GenerateContentConfig(
                    response_modalities=[google_types.Modality.IMAGE, google_types.Modality.TEXT]
                )
                response = self.client.models.generate_content(
                    model=self.model_version, contents=prompt, config=gen_cfg,
                )
                paths = []
                for i, part in enumerate(response.candidates[0].content.parts):
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        img = Image.open(BytesIO(inline.data))
                        path = os.path.join(self.save_folder, f"{file_prefix}_{i + 1}.png")
                        img.save(path)
                        paths.append(path)
                return {"url": paths[0] if len(paths) == 1 else paths,
                        "seed": None, "model": self.model_version}

    @classmethod
    def list_available_models(cls, provider: str) -> List[str]:
        """Return available image model IDs for a given provider."""
        return MODELS.get(provider.lower(), {}).get("image", [])
