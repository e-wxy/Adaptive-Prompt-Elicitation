"""Core Project class for Adaptive Prompt Elicitation."""
import json
import os
from typing import Optional

import numpy as np
import pandas as pd

from .logger import create_logger
from .questioners import (
    QuestionGeneratorAPE,
    QuestionGeneratorInContextQuery,
    QuestionGeneratorMC,
    QuestionGeneratorVanilla,
)
from .utils import (
    DEFAULT_MODELS,
    ImageGenerator,
    LLMAgent,
    parse_llm_output_to_json,
    convert_log_to_json_array,
    download_image,
    json_to_html,
    load_prompt,
    save_images,
)

_QUESTIONER_MAP = {
    "APE":              QuestionGeneratorAPE, 
    "In-Context":       QuestionGeneratorInContextQuery, 
    "Vanilla":          QuestionGeneratorVanilla,
    "APE-MC":           QuestionGeneratorMC,
}

_DEFAULT_N = 5   # candidate questions per round
_DEFAULT_M = 5   # options per question


class Project:
    """Interactive design project that elicits user requirements via adaptive Q&A.

    Example usage::

        project = Project(
            task="App Icon",
            description="Icon design for a hiking app with a mountain and sun motif",
            questioner="APE",   # proposed method
        )
        question = project.ask_questions(json_format=False)
        print(question)
        project.record_answer("Modern, minimalist style with bold typography")
        project.extract_requirements()
    """

    def __init__(
        self,
        task: str = "Poster",
        description: str = "",
        name: str = "",
        id: Optional[int] = None,
        seed: Optional[int] = None,
        questioner: str = "APE",
        # LLM configuration
        llm_provider: str = "openai",
        llm_model: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        # Image generation configuration
        img_provider: str = "fal",
        img_model: Optional[str] = None,
        img_api_key: Optional[str] = None,
        # Misc
        prompt_folder: Optional[str] = None,
        verbose: bool = True,
        log_file: Optional[str] = None,
    ):
        """
        Args:
            task: High-level design task (e.g. "Poster", "Logo").
            description: Initial free-text description from the user.
            name: Project name for logging; defaults to ``task``.
            id: Project run ID (for reproducibility tracking).
            seed: Random seed; sampled if None.
            questioner: Strategy — "APE" (default, proposed method),
                "In-Context Query" (interactive baseline), "Vanilla", or "APE-MC".
            llm_provider: LLM provider — "openai", "anthropic", "vertex", or "google".
            llm_model: Specific LLM model ID; uses provider default if None.
            llm_api_key: API key; read from environment variable if None.
            img_provider: Image generation provider — "fal" or "openai".
            img_model: Image model ID; uses provider default if None.
            img_api_key: API key; read from environment variable if None.
            prompt_folder: Path to the folder containing prompt templates.
            verbose: When True, regenerate the image after each update.
            log_file: Resume an existing session from this log file path.
        """
        self.task = task
        self.description = description
        self.project_name = name or task
        self.project_id = id if id is not None else 1
        self.seed = seed if seed is not None else int(np.random.randint(0, 10000))
        self.prompt_folder = prompt_folder
        self.verbose = verbose
        self.requirements: dict = {}

        self.max_img_length = 512

        # Build LLM and image generation clients
        self.llm_agent = LLMAgent(
            provider=llm_provider,
            api_key=llm_api_key,
            model_version=llm_model,
        )
        self.image_generator = ImageGenerator(
            provider=img_provider,
            api_key=img_api_key,
            model_version=img_model,
        )

        # Current state
        self.last_question: Optional[str] = None
        self.last_answer: Optional[str] = None
        self.image_prompt: Optional[str] = None
        self.img_url: Optional[str] = None

        # Logger
        if log_file is None:
            self.logger, self.log_file = create_logger(
                name=f"{task}_{self.project_name}_{self.project_id}"
            )
            self._init_task(task, description)
        else:
            self.logger, self.log_file = self._init_from_log_file(log_file)

        # Questioner
        if questioner not in _QUESTIONER_MAP:
            raise ValueError(
                f"Unknown questioner '{questioner}'. Choose from: {list(_QUESTIONER_MAP)}."
            )
        self.questioner = _QUESTIONER_MAP[questioner](
            llm_agent=self.llm_agent,
            prompt_folder=self.prompt_folder,
            temperature=0.7,
            seed=self.seed,
            logger=self.logger,
        )

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_task(self, task: str, description: str):
        """Extract initial requirements from the user description and generate a first image."""
        self.logger.info(
            "Initialize Project",
            extra={"role": "user", "content": {
                "task": task, "description": description,
                "project_name": self.project_name,
                "project_id": self.project_id, "seed": self.seed,
            }},
        )

        if description:
            prompt = load_prompt("init_task.md", self.prompt_folder).format(
                design_type=task, user_input=description,
            )
            system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
            response = self.llm_agent.call(prompt=prompt, system_prompt=system_prompt)["text"]
            output_json = parse_llm_output_to_json(response)

            self.logger.info("Init Requirements", extra={"role": "assistant", "content": output_json})

            requirements = output_json.get("Requirements", {})
            if not isinstance(requirements, dict):
                raise ValueError("Expected 'Requirements' to be a dict.")
            self.requirements = requirements

        if self.verbose:
            self.get_image_prompt()
            self.generate_image()

    def _init_from_log_file(self, log_file: str):
        """Restore project state from an existing session log."""
        if not os.path.exists(log_file):
            raise FileNotFoundError(f"Log file not found: {log_file}")
        logger, log_file = create_logger(log_file=log_file)
        self.load_history(log_file)
        logger.info(
            "Project loaded from log file",
            extra={"role": "system", "content": {
                "task": self.task, "description": self.description,
                "project_name": self.project_name, "project_id": self.project_id,
                "seed": self.seed, "requirements": self.requirements,
            }},
        )
        return logger, log_file

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    def get_requirements(self) -> str:
        """Return the current requirements as a formatted JSON string."""
        return json.dumps(self.requirements, indent=2)

    def get_last_question(self) -> Optional[str]:
        """Return the most recently asked question string."""
        return self.last_question

    def get_last_answer(self) -> Optional[str]:
        """Return the most recently recorded answer."""
        return self.last_answer

    # ------------------------------------------------------------------
    # Requirements management
    # ------------------------------------------------------------------

    def extract_requirements(self, question: Optional[str] = None,
                             answer: Optional[str] = None):
        """Update requirements based on a Q&A exchange.

        Args:
            question: The question that was asked (defaults to ``last_question``).
            answer: The user's answer (defaults to ``last_answer``).
        """
        question = question or self.get_last_question()
        answer = answer or self.get_last_answer()

        prompt = load_prompt("requirement_transformation.md", self.prompt_folder).format(
            task=self.task, requirements=self.get_requirements(),
            question=question, answer=answer,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(prompt=prompt, system_prompt=system_prompt)["text"]
        response = parse_llm_output_to_json(response)

        self.logger.info("Extract Requirements", extra={"role": "assistant", "content": response})
        self.requirements = response["Requirements"]

        if self.verbose:
            self.get_image_prompt()
            self.generate_image()

    def add_requirement(self, user_input: str):
        """Append a free-text user requirement to the current requirement set.

        Args:
            user_input: Natural-language requirement from the user.
        """
        self.logger.info("Add Requirement", extra={"role": "user", "content": user_input})
        prompt = load_prompt("requirement_addition.md", self.prompt_folder).format(
            task=self.task, requirements=self.get_requirements(), user_input=user_input,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(prompt=prompt, system_prompt=system_prompt)["text"]
        result = parse_llm_output_to_json(response)
        self.logger.info("Update Requirement", extra={"role": "assistant", "content": result})
        self.requirements = result["Requirements"]

        if self.verbose:
            self.get_image_prompt()
            self.generate_image()

    def set_requirements(self, requirements: dict):
        """Override requirements directly with the provided dict."""
        if not isinstance(requirements, dict):
            raise ValueError("Requirements must be a dict.")
        self.requirements = requirements
        self.logger.info("Set Requirements", extra={"role": "user", "content": requirements})
        if self.verbose:
            self.get_image_prompt()
            self.generate_image()

    # ------------------------------------------------------------------
    # Question asking
    # ------------------------------------------------------------------

    def ask_questions(self, N: int = _DEFAULT_N, M: int = _DEFAULT_M,
                      json_format: bool = True):
        """Generate and return the next clarifying question.

        Args:
            N: Number of candidate questions to generate internally.
            M: Number of answer options per question.
            json_format: If True, return the full question JSON; otherwise
                return a human-readable string with numbered options.

        Returns:
            Question JSON (dict) or formatted string.
        """
        question_json = self.questioner.get_next_question(
            self.task, self.get_requirements(), N, M,
        )

        option_list = sorted(
            [opt for opt in question_json["options"] if opt.lower() != "other"]
        )
        options_str = "".join(
            f"{i + 1}. {opt}\n" for i, opt in enumerate(option_list)
        ) + f"{len(option_list) + 1}. Other (please specify)"
        question_str = f"{question_json['question']}\nOptions:\n{options_str}"

        self.logger.info("Ask Question", extra={"role": "assistant", "content": question_json})
        self.last_question = question_str

        return question_json if json_format else question_str

    def ask_visual_questions(self, N: int = _DEFAULT_N, M: int = _DEFAULT_M) -> dict:
        """Generate a question with image-based option previews (synchronous convenience wrapper).

        Returns:
            Question JSON with each option containing "url", "prompt", and "probability".
        """
        question_json = self.ask_visual_question_text(N, M)
        question_json = self.finalize_visual_question(question_json)
        for _ in self.fetch_visual_question_images(question_json):
            pass
        return question_json

    # ------------------------------------------------------------------
    # Staged visual question API (used by the web streaming endpoint)
    # ------------------------------------------------------------------

    def ask_visual_question_text(self, N: int = _DEFAULT_N, M: int = _DEFAULT_M) -> dict:
        """Step 1 — generate question text and raw option labels from the questioner.

        Returns:
            Question JSON ``{question, feature, options: {opt: probability}}``
            (no image prompts or URLs yet).
        """
        return self.questioner.get_next_question(
            self.task, self.get_requirements(), N, M,
        )

    def finalize_visual_question(self, question_json: dict) -> dict:
        """Step 2 — generate image prompts for each option and set ``last_question``.

        Mutates and returns *question_json* with options restructured to
        ``{opt: {prompt, probability}}``.
        """
        option_items = [
            (opt, prob)
            for opt, prob in question_json["options"].items()
            if opt.lower() != "other"
        ]
        option_list_sorted = sorted(option_items, key=lambda x: x[0])
        options_str = "".join(
            f"{i + 1}. {opt}\n" for i, (opt, _) in enumerate(option_list_sorted)
        ) + f"{len(option_items) + 1}. Other (please specify)"
        self.last_question = f"{question_json['question']}\nOptions:\n{options_str}"

        option_img_prompts = self.get_option_image_prompt(question_json)
        question_json["options"] = {
            opt: {"prompt": prompt, "probability": prob}
            for (opt, prob), prompt in zip(option_items, option_img_prompts)
        }
        return question_json

    def fetch_visual_question_images(self, question_json: dict, size: str = "small",
                                      n: int = 1, seed: Optional[int] = None):
        """Step 3 — generate option images concurrently, yielding ``(option, url)`` as each completes.

        Mutates *question_json* in-place, adding ``"url"`` to each option entry.
        Logs the completed question when all images are ready.

        Yields:
            Tuples of ``(option_label, image_url)`` in completion order.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed as futures_as_completed

        seed = seed if seed is not None else self.seed
        options = list(question_json["options"].items())

        def _generate(item):
            opt, data = item
            url = self.image_generator.generate_image(
                prompt=data["prompt"], size=size, n=n, seed=seed,
            )["url"]
            return opt, url

        with ThreadPoolExecutor(max_workers=len(options)) as executor:
            futures = {executor.submit(_generate, item): item[0] for item in options}
            for future in futures_as_completed(futures):
                opt, url = future.result()
                question_json["options"][opt]["url"] = url
                yield opt, url

        self.logger.info("Ask Question", extra={"role": "assistant", "content": question_json})

    def record_answer(self, answer: str) -> str:
        """Record a real user's answer to the last question.

        Args:
            answer: The user's answer string.
        """
        self.last_answer = answer
        self.logger.info("Answer", extra={"role": "user", "content": answer})
        return answer

    def answer_question(self, user, question: Optional[str] = None) -> str:
        """Obtain and record an answer from a simulated user.

        Args:
            user: A ``User`` or ``UserVision`` instance with a ``get_answer`` method.
            question: Question string (defaults to ``last_question``).
        """
        question = question or self.get_last_question()
        answer = user.get_answer(question)
        self.last_answer = answer
        return answer

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    def get_image_prompt(self, requirements: Optional[str] = None) -> str:
        """Generate an optimised image prompt from the current requirements.

        Returns:
            The image prompt string.
        """
        prompt = load_prompt("image_prompt.md", self.prompt_folder).format(
            task=self.task,
            requirements=requirements or self.get_requirements(),
            max_length=self.max_img_length,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(prompt=prompt, system_prompt=system_prompt, logprobs=False)
        image_prompt = response["text"]
        self.logger.info("Image Prompt", extra={"role": "assistant", "content": image_prompt})
        self.image_prompt = image_prompt
        return image_prompt

    def generate_image(self, image_prompt: Optional[str] = None,
                       size: str = "large", n: int = 1,
                       seed: Optional[int] = None) -> str:
        """Generate an image from the current image prompt.

        Args:
            image_prompt: Prompt override; uses ``self.image_prompt`` if None.
            size: Size hint passed to the image generator.
            n: Number of images to generate.
            seed: Seed override; uses ``self.seed`` if None.

        Returns:
            URL or local path of the generated image.
        """
        image_prompt = image_prompt or self.image_prompt
        seed = seed if seed is not None else self.seed
        result = self.image_generator.generate_image(
            prompt=image_prompt, size=size, n=n, seed=seed,
        )
        image_url = result["url"]
        self.img_url = image_url
        self.logger.info(
            "Generate Image",
            extra={"role": "system", "content": {
                "image_url": image_url, "image_prompt": image_prompt, "seed": seed,
            }},
        )
        return image_url

    def set_image_prompt(self, new_prompt: str, regenerate: bool = True):
        """Override the image prompt directly and optionally regenerate the image.

        Args:
            new_prompt: New image prompt text.
            regenerate: Whether to immediately generate a new image.
        """
        if not isinstance(new_prompt, str) or not new_prompt.strip():
            raise ValueError("image_prompt must be a non-empty string.")
        self.image_prompt = new_prompt
        self.logger.info("Set Image Prompt", extra={"role": "user", "content": new_prompt})
        if regenerate:
            self.generate_image()

    def change_image_model(self, provider: str, model_version: str,
                           api_key: Optional[str] = None):
        """Switch the image generation backend at runtime.

        Args:
            provider: New provider (e.g. "fal", "openai").
            model_version: Model ID for the new provider.
            api_key: API key for the new provider.
        """
        self.image_generator = ImageGenerator(
            provider=provider, api_key=api_key, model_version=model_version,
        )
        self.logger.info(
            "Change Image Model",
            extra={"role": "system", "content": {"provider": provider, "model_version": model_version}},
        )

    def get_option_image_prompt(self, question: dict) -> list:
        """Generate image prompts for each option in a question.

        Args:
            question: Question JSON with "feature", "question", and "options" keys.

        Returns:
            List of image prompt strings, one per option.
        """
        options_str = "".join(
            f"- {opt}\n" for opt in question["options"] if opt.lower() != "other"
        )
        prompt = load_prompt("image_option_prompt.md", self.prompt_folder).format(
            task=self.task, requirements=self.requirements,
            feature=question["feature"], question=question["question"],
            list_of_values=options_str,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(prompt=prompt, system_prompt=system_prompt, logprobs=False)
        entries = parse_llm_output_to_json(response["text"])
        return [entry["prompt"] for entry in entries]

    def generate_option_images(self, question: dict, size: str = "small",
                               n: int = 1, seed: Optional[int] = None):
        """Generate preview images for each answer option.

        Args:
            question: Question JSON.
            size: Image size hint.
            n: Images per option.
            seed: Seed override.

        Returns:
            Tuple of (image_urls, option_prompts).
        """
        option_prompts = self.get_option_image_prompt(question)
        image_urls = []
        for img_prompt in option_prompts:
            url = self.image_generator.generate_image(
                prompt=img_prompt, size=size, n=n,
                seed=seed if seed is not None else self.seed,
            )["url"]
            image_urls.append(url)
        return image_urls, option_prompts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_final(self):
        """Write a final summary log entry and flush logs to JSON."""
        self.logger.info(
            "Save Final",
            extra={"role": "system", "content": {
                "task": self.task, "project_name": self.project_name,
                "project_id": self.project_id, "image_prompt": self.image_prompt,
                "image_url": self.img_url, "requirements": self.requirements,
            }},
        )
        convert_log_to_json_array(self.log_file)

    def save_images(self, save_folder: str = "outputs/images/"):
        """Download and save all generated images from the session log.

        Also writes a ``results.csv`` with image metadata.
        """
        save_folder = os.path.join(save_folder, f"{self.project_name}/{self.project_id}")
        os.makedirs(save_folder, exist_ok=True)
        df = pd.DataFrame(columns=["image_url", "image_prompt", "seed", "iteration"])
        t = 0
        for entry in self.load_history_log():
            if entry.get("message") == "Generate Image":
                t += 1
                image_url = entry["content"]["image_url"]
                img = download_image(image_url)
                if img:
                    img.save(os.path.join(save_folder, f"{t}.png"))
                df.loc[len(df)] = {
                    "image_url": image_url,
                    "image_prompt": entry["content"]["image_prompt"],
                    "seed": entry["content"]["seed"],
                    "iteration": t,
                }
        df.to_csv(os.path.join(save_folder, "results.csv"), index=False)

    def regenerate_images(self, size: str = "large", n: int = 4,
                          seed: Optional[int] = None,
                          save_folder: str = "outputs/images/"):
        """Regenerate images from stored prompts in the session log.

        Useful for producing high-resolution variants of all session images.
        """
        save_folder = os.path.join(save_folder, f"{self.project_name}/{self.project_id}")
        os.makedirs(save_folder, exist_ok=True)
        for t, entry in enumerate(
            e for e in self.load_history_log() if e.get("message") == "Generate Image"
        ):
            image_prompt = entry["content"].get("image_prompt")
            if image_prompt:
                result = self.image_generator.generate_image(
                    prompt=image_prompt, size=size, n=n, seed=seed,
                )
                save_images(result["url"], save_folder, file_prefix=str(t + 1))
                self.logger.info(
                    "Regenerate Image",
                    extra={"role": "system", "content": {
                        "image_url": result["url"], "image_prompt": image_prompt,
                        "seed": seed, "step": t + 1,
                    }},
                )

    # ------------------------------------------------------------------
    # Log loading / history
    # ------------------------------------------------------------------

    def load_history_log(self, file_path: Optional[str] = None) -> list:
        """Load log entries from a JSONL file.

        Returns:
            List of log entry dicts.
        """
        file_path = file_path or self.log_file
        if not os.path.exists(file_path):
            return []
        entries = []
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def load_history(self, file_path: Optional[str] = None):
        """Restore project state from a session log file."""
        log_data = self.load_history_log(file_path)
        initial = self._retrieve_initial(file_path)
        self.task = initial.get("task", self.task)
        self.description = initial.get("description", self.description)
        self.project_name = initial.get("project_name", self.project_name)
        self.project_id = initial.get("project_id", self.project_id)
        self.seed = initial.get("seed", self.seed)

        requirements = [
            e["content"].get("requirements") or e.get("content", {})
            for e in log_data
            if e.get("message") == "Extract Requirements"
        ]
        if requirements:
            self.requirements = requirements[-1]

        prompts = [e["content"]["image_prompt"] for e in log_data if e.get("message") == "Generate Image"]
        urls = [e["content"]["image_url"] for e in log_data if e.get("message") == "Generate Image"]
        self.image_prompt = prompts[-1] if prompts else self.image_prompt
        self.img_url = urls[-1] if urls else self.img_url

    def _retrieve_initial(self, log_file: Optional[str] = None) -> dict:
        for entry in self.load_history_log(log_file):
            if entry.get("message") == "Initialize Project":
                return entry.get("content", {})
        return {}

    def retrieve_process(self, log_file: Optional[str] = None) -> dict:
        """Return a per-iteration snapshot of the session (questions, answers, images)."""
        logs = self.load_history_log(log_file)
        iterations: dict = {}
        iter_num = 0
        current: dict = {}
        for entry in logs:
            msg = entry.get("message", "")
            if entry.get("role") == "user":
                current["user_input"] = f"[{msg}]: {entry.get('content', {})}"
            if msg == "Generate Image":
                current["image_url"] = entry["content"]["image_url"]
                current["image_prompt"] = entry["content"]["image_prompt"]
                current["seed"] = entry["content"]["seed"]
                iterations[iter_num] = dict(current)
                iter_num += 1
                current = {}
            elif msg.endswith("Requirements"):
                current["requirements"] = entry["content"].get("Requirements") or entry["content"]
            elif msg == "Ask Question":
                current["question"] = entry["content"]
            elif msg == "Answer":
                current["answer"] = entry.get("content", "")
            elif msg == "Question Candidates":
                current["question_candidates"] = entry["content"]
        if current:
            iterations[iter_num] = dict(current)
        return iterations

    # ------------------------------------------------------------------
    # Display helpers (Jupyter / HTML)
    # ------------------------------------------------------------------

    def get_conversation(self) -> str:
        """Build an HTML representation of the conversation history."""
        logs = self.load_history_log()
        parts = []
        for entry in logs:
            role = (entry.get("role") or "").lower()
            msg = entry.get("message")
            content = entry.get("content")

            if msg == "Initialize Project" and role == "user" and isinstance(content, dict):
                parts.append(
                    f"<div><p><strong>User:</strong> "
                    f"{content.get('task')}: {content.get('description')}</p></div>"
                )
            elif msg == "Ask Question" and role == "assistant" and isinstance(content, dict):
                q_text = content.get("question", "")
                options = content.get("options", {})
                html = [f"<p><strong>Assistant:</strong></p><div>{q_text}</div>"]
                if isinstance(options, dict) and options:
                    html.append("<ul>")
                    for opt, prob in options.items():
                        prob_val = prob.get("probability") if isinstance(prob, dict) else prob
                        html.append(f"<li>{opt}: {prob_val}</li>")
                    html.append("</ul>")
                parts.append("".join(html))
            elif msg == "Answer" and role == "user":
                answer = (
                    content.get("Answer") or content.get("answer") or content
                    if isinstance(content, dict) else content
                )
                parts.append(f"<p><strong>User:</strong></p><div>{answer}</div>")

        return "\n".join(parts) if parts else "<p>No conversation yet.</p>"

    def display_requirements(self) -> str:
        """Return an HTML string showing the current requirements."""
        html = f"<h2>{self.task.capitalize()}</h2>"
        html += json_to_html(self.requirements) if self.requirements else "<p>No requirements yet.</p>"
        return html

    def display_conversation(self, n: Optional[int] = None) -> str:
        """Return an HTML conversation history, optionally trimmed to the last ``n`` turns."""
        html = self.get_conversation()
        if n is not None and html != "<p>No conversation yet.</p>":
            items = html.split("\n")
            html = "\n".join(items[-n:] if n < 0 else items[:n])
        return html

    def display_visual_questions(self, n: Optional[int] = None) -> str:
        """Return an HTML block showing visual questions with image options."""
        logs = self.load_history_log()
        question_htmls = []
        for entry in logs:
            if entry.get("message") != "Ask Question":
                continue
            content = entry.get("content", {})
            options = content.get("options", {})
            if not any(isinstance(v, dict) and "url" in v for v in options.values()):
                continue
            idx = len(question_htmls) + 1
            html = (
                f'<h3>Q{idx}: {content.get("question", "")}</h3>'
                '<div style="display:flex;gap:1em;flex-wrap:wrap;">'
            )
            for i, (opt, value) in enumerate(sorted(options.items())):
                if not isinstance(value, dict) or "url" not in value:
                    continue
                html += (
                    f'<div style="max-width:30%">'
                    f"<p>{i + 1}. {opt}</p>"
                    f'<img src="{value["url"]}" alt="{opt}" style="width:100%"/>'
                    f"<p>{value.get('prompt', '')}</p></div>"
                )
            html += "</div>"
            question_htmls.append(html)

        if not question_htmls:
            return "<p>No visual questions yet.</p>"
        if n is not None and len(question_htmls) > abs(n):
            question_htmls = question_htmls[-n:] if n < 0 else question_htmls[:n]
        return "<br/>".join(question_htmls)
