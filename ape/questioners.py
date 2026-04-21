"""Question generation strategies for prompt elicitation."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

import numpy as np

from .logger import create_logger
from .utils import LLMAgent, parse_llm_output_to_json, load_prompt

# Default candidates and options per question
_DEFAULT_N = 5
_DEFAULT_M = 5


def _sanitize_probabilities(answers: dict) -> dict:
    """Coerce probability values to floats, replacing missing/None with 0."""
    for q in answers.values():
        if "probabilities" in q:
            q["probabilities"] = {
                opt: float(val) if str(val).strip() not in ("", "None") else 0.0
                for opt, val in q["probabilities"].items()
            }
    return answers


class QuestionGeneratorVanilla:
    """Vanilla interactive baseline.
     
    Generates one question without uncertainty estimation."""

    def __init__(self, llm_agent: LLMAgent, prompt_folder: Optional[str] = None,
                 temperature: float = 0.7, seed: Optional[int] = None, logger=None):
        self.llm_agent = llm_agent
        self.prompt_folder = prompt_folder
        self.temperature = temperature
        self.seed = seed
        self.logger = logger or create_logger()[0]

    def get_next_question(self, task: str, requirements: str,
                          N: int = _DEFAULT_N, M: int = _DEFAULT_M) -> Dict[str, Any]:
        """Generate and return the next question to ask the user.

        Returns:
            Dict with keys: "question", "options", "feature", "visual_influence_factor".
        """
        prompt = load_prompt("query_generation_vanilla.md", self.prompt_folder).format(
            task=task, requirements=requirements, M=M,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(
            prompt=prompt, system_prompt=system_prompt,
            temperature=self.temperature, seed=self.seed, max_tokens=2048,
        )
        question = parse_llm_output_to_json(response["text"])

        # Normalize options list → uniform-probability dict
        if "options" in question and isinstance(question["options"], list):
            options = question["options"]
            prob = 1.0 / len(options) if options else 0.0
            question["options"] = {opt: prob for opt in options}

        return question


class QuestionGeneratorInContextQuery(QuestionGeneratorVanilla):
    """In-Context Query baseline.

    Generates queries using LLM in-context reasoning.
    """

    def get_next_question(self, task: str, requirements: str,
                          N: int = _DEFAULT_N, M: int = _DEFAULT_M) -> Dict[str, Any]:
        prompt = load_prompt("query_generation_cot.md", self.prompt_folder).format(
            task=task, requirements=requirements, M=M,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(
            prompt=prompt, system_prompt=system_prompt,
            temperature=self.temperature, seed=self.seed, max_tokens=2048,
        )
        return parse_llm_output_to_json(response["text"])


class QuestionGeneratorAPE(QuestionGeneratorVanilla):
    """Adaptive Prompt Elicitation (APE).

    Generates queries grounded in an information-theoretic framework.
    """

    def _generate_candidates(self, task: str, requirements: str,
                              N: int, M: int) -> list:
        """Generate N candidate questions with estimated probabilities."""
        prompt = load_prompt("query_generation_with_estimation.md", self.prompt_folder).format(
            task=task, requirements=requirements, N=N, M=M,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(
            prompt=prompt, system_prompt=system_prompt,
            temperature=self.temperature, seed=self.seed, max_tokens=2048,
        )
        questions = parse_llm_output_to_json(response["text"])

        for item in questions:
            if not all(k in item for k in ("question", "options", "feature", "visual_influence_factor")):
                raise ValueError("Missing required fields in question candidate.")
            if not isinstance(item["options"], dict):
                raise ValueError("`options` must be a dict mapping option → probability.")
            if not isinstance(item["visual_influence_factor"], (int, float)):
                raise ValueError("`visual_influence_factor` must be numeric.")

        return questions

    @staticmethod
    def _weighted_entropy(questions: list) -> list:
        """Compute weighted EIG (entropy × visual_influence_factor) for each question."""
        for q in questions:
            probs = list(q["options"].values())
            entropy = -sum(p * np.log(p) for p in probs if p > 0)
            q["wEIG"] = q["visual_influence_factor"] * entropy
        return questions

    def get_next_question(self, task: str, requirements: str,
                          N: int = _DEFAULT_N, M: int = _DEFAULT_M) -> Dict[str, Any]:
        questions = self._generate_candidates(task, requirements, N, M)
        questions = self._weighted_entropy(questions)
        self.logger.info("Question Candidates", extra={"role": "assistant", "content": questions})
        return max(questions, key=lambda q: q["wEIG"])


class QuestionGeneratorMC(QuestionGeneratorVanilla):
    """APE variant with Monte Carlo estimation.

    Generates N candidate visual queries, then estimates option probabilities via
    ``N_s`` parallel LLM calls with diverse prompt variants.
    """

    def _generate_candidates(self, task: str, requirements: str,
                              N: int, M: int) -> Dict[str, Any]:
        """Generate N candidate questions (options as a list, no probabilities yet)."""
        prompt = load_prompt("query_generation.md", self.prompt_folder).format(
            task=task, requirements=requirements, N=N, M=M,
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(
            prompt=prompt, system_prompt=system_prompt,
            temperature=self.temperature, seed=self.seed, max_tokens=2048,
        )
        return parse_llm_output_to_json(response["text"])

    def _sample_probabilities(self, task: str, requirements: str,
                               questions: Dict[str, Any], sample_idx: int) -> Dict[str, Any]:
        """Estimate option probabilities using the i-th prompt variant."""
        filtered = {
            qid: {"question": q["question"], "options": q["options"]}
            for qid, q in questions.items()
        }
        prompt = load_prompt(f"answer_estimation_{sample_idx}.md", self.prompt_folder).format(
            task=task, requirements=requirements, questions=json.dumps(filtered, indent=2),
        )
        system_prompt = load_prompt("system_prompt.md", self.prompt_folder)
        response = self.llm_agent.call(
            prompt=prompt, system_prompt=system_prompt,
            temperature=self.temperature, seed=self.seed, max_tokens=2048,
        )
        answers = parse_llm_output_to_json(response["text"])
        answers = _sanitize_probabilities(answers)
        self.logger.info(f"MC Sample {sample_idx}", extra={"role": "assistant", "content": answers})
        return answers

    def _estimate_probabilities(self, task: str, requirements: str,
                                 questions: Dict[str, Any], N_s: int = 3) -> Dict[str, Any]:
        """Run N_s probability samples in parallel and average the results."""
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(self._sample_probabilities, task, requirements, questions, i + 1)
                for i in range(N_s)
            ]
            samples = [f.result() for f in as_completed(futures)]

        for qid, q in questions.items():
            options = {}
            for opt in q["options"]:
                probs = [float(s[qid]["probabilities"].get(opt, 0)) for s in samples]
                options[opt] = float(np.mean(probs))
            q["options"] = options
        return questions

    @staticmethod
    def _compute_weighted_eig(questions: Dict[str, Any]) -> Dict[str, Any]:
        """Compute weighted EIG for each question."""
        for q in questions.values():
            probs = list(q["options"].values())
            entropy = -sum(p * np.log(p) for p in probs if p > 0)
            q["wEIG"] = q["visual_influence_factor"] * entropy
        return questions

    def get_next_question(self, task: str, requirements: str,
                          N: int = _DEFAULT_N, M: int = _DEFAULT_M,
                          N_s: int = 3) -> Dict[str, Any]:
        """Select the highest-EIG question via MC probability estimation.

        Args:
            N: Number of candidate questions to generate.
            M: Number of answer options per question.
            N_s: Number of MC probability samples (uses ``answer_estimation_1..N_s.md``).
        """
        questions = self._generate_candidates(task, requirements, N, M)
        questions = self._estimate_probabilities(task, requirements, questions, N_s)
        questions = self._compute_weighted_eig(questions)
        self.logger.info("Question Candidates", extra={"role": "assistant", "content": questions})
        return max(questions.values(), key=lambda q: q["wEIG"])
