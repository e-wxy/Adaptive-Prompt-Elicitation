"""Evaluation metrics for text-to-image alignment.

Provides similarity scoring classes for both image-image and text-text comparisons:

- ``CLIPScore``           — image↔image and text↔image via CLIP.
- ``DINOV2Score``         — image↔image via DINOv2.
- ``DreamSimScore``       — image↔image perceptual similarity via DreamSim.
- ``E5Text``              — text↔text via E5-large.
- ``OpenAITextEmbedding`` — text↔text via OpenAI text-embedding-3-large.

All classes share the ``get_similarity(a, b)`` and ``get_similarities(list_a, list_b)`` API.
Paths ending with an image extension are treated as images; all others as text.
"""
import os

import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from transformers import (
    AutoImageProcessor,
    AutoModel,
    AutoTokenizer,
    CLIPModel,
    CLIPProcessor,
)

load_dotenv()

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_default_device(device)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class Similarity:
    """Base class for similarity scoring.

    Subclasses implement ``get_image_embedding`` and/or ``get_text_embedding``.
    """

    def __init__(self, model=None, processor=None):
        self.model = model
        self.processor = processor

    @staticmethod
    def _is_image(path: str) -> bool:
        return any(path.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS)

    def preprocess_image(self, image_path: str) -> Image.Image:
        return Image.open(image_path).convert("RGB")

    def get_image_embedding(self, path: str) -> torch.Tensor:
        raise NotImplementedError

    def get_text_embedding(self, text: str) -> torch.Tensor:
        raise NotImplementedError

    def normalize(self, embedding: torch.Tensor) -> torch.Tensor:
        return F.normalize(embedding, p=2, dim=-1)

    def get_embedding(self, input: str) -> torch.Tensor:
        emb = self.get_image_embedding(input) if self._is_image(input) else self.get_text_embedding(input)
        return self.normalize(emb)

    def cosine_similarity(self, emb1: torch.Tensor, emb2: torch.Tensor) -> torch.Tensor:
        return torch.matmul(emb1, emb2.T)

    @torch.no_grad()
    def get_similarity(self, input1: str, input2: str) -> float:
        """Compute cosine similarity between two inputs (image paths or text strings)."""
        return self.cosine_similarity(self.get_embedding(input1), self.get_embedding(input2)).item()

    @torch.no_grad()
    def get_similarities(self, inputs1: list, inputs2: list):
        """Compute a similarity matrix between two lists of inputs.

        Returns:
            np.ndarray of shape (len(inputs1), len(inputs2)).
        """
        embs1 = torch.cat([self.get_embedding(x) for x in inputs1], dim=0)
        embs2 = torch.cat([self.get_embedding(x) for x in inputs2], dim=0)
        return self.cosine_similarity(embs1, embs2).cpu().numpy()


class CLIPScore(Similarity):
    """Image↔image and text↔image similarity via CLIP (ViT-B/32 by default)."""

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32"):
        self.processor = CLIPProcessor.from_pretrained(model_name)
        model = CLIPModel.from_pretrained(model_name).eval()
        super().__init__(model=model, processor=self.processor)

    def get_text_embedding(self, text: str) -> torch.Tensor:
        inputs = self.processor(text=[text], return_tensors="pt", padding=True, truncation=True)
        return self.model.get_text_features(**inputs)

    def get_image_embedding(self, path: str) -> torch.Tensor:
        image = self.preprocess_image(path)
        inputs = self.processor(images=image, return_tensors="pt").to(device)
        return self.model.get_image_features(**inputs)


class DINOV2Score(Similarity):
    """Image↔image similarity via DINOv2 (facebook/dinov2-large by default).

    Only image inputs are supported.
    """

    def __init__(self, model_name: str = "facebook/dinov2-large"):
        processor = AutoImageProcessor.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name).eval()
        super().__init__(model=model, processor=processor)

    def get_text_embedding(self, text: str) -> torch.Tensor:
        raise NotImplementedError("DINOv2 does not support text inputs.")

    def get_image_embedding(self, path: str) -> torch.Tensor:
        image = self.preprocess_image(path)
        inputs = self.processor(images=image, return_tensors="pt").to(device)
        outputs = self.model(**inputs)
        return outputs.last_hidden_state[:, 0]


class DreamSimScore(Similarity):
    """Image↔image perceptual similarity via DreamSim.

    Only image inputs are supported.
    """

    def __init__(self):
        from dreamsim import dreamsim
        model, processor = dreamsim(pretrained=True)
        super().__init__(model=model, processor=processor)

    def preprocess_image(self, path: str) -> Image.Image:
        return Image.open(path)

    def get_text_embedding(self, text: str) -> torch.Tensor:
        raise NotImplementedError("DreamSim only supports image inputs.")

    def get_image_embedding(self, path: str) -> torch.Tensor:
        image = self.preprocess_image(path)
        embedding = self.processor(image).to(device)
        return self.model.embed(embedding)


class E5Text(Similarity):
    """Text↔text similarity via E5-large-v2."""

    def __init__(self, model_name: str = "intfloat/e5-large-v2"):
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        super().__init__(model=model, processor=tokenizer)

    def get_text_embedding(self, text: str) -> torch.Tensor:
        if not text.lower().startswith(("query:", "passage:")):
            text = "query: " + text
        inputs = self.processor(text, return_tensors="pt", padding=True, truncation=True)
        outputs = self.model(**inputs)
        return outputs.last_hidden_state.mean(dim=1)

    def get_image_embedding(self, path: str) -> torch.Tensor:
        raise NotImplementedError("E5Text only supports text inputs.")


class OpenAITextEmbedding(Similarity):
    """Text↔text similarity via OpenAI text-embedding-3-large."""

    def __init__(self, model_name: str = "text-embedding-3-large"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
        self.model_name = model_name
        super().__init__()

    def get_text_embedding(self, text: str) -> torch.Tensor:
        response = self.client.embeddings.create(model=self.model_name, input=text)
        return torch.tensor(response.data[0].embedding).unsqueeze(0)

    def get_embedding(self, input: str) -> torch.Tensor:
        if self._is_image(input):
            raise ValueError("OpenAITextEmbedding only supports text inputs.")
        return self.normalize(self.get_text_embedding(input))


_REGISTRY = {
    "clip": CLIPScore,
    "clipscore": CLIPScore,
    "dinov2": DINOV2Score,
    "dreamsim": DreamSimScore,
    "e5": E5Text,
    "e5text": E5Text,
    "openai": OpenAITextEmbedding,
    "openai_text_embedding": OpenAITextEmbedding,
}


def get_similarity_model(name: str) -> Similarity:
    """Instantiate a similarity model by name.

    Supported names: "clip", "dinov2", "dreamsim", "e5", "openai".
    """
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(f"Unknown model '{name}'. Choose from: {list(_REGISTRY)}.")
    return cls()
