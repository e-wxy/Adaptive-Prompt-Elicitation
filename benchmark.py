"""Automated benchmarking of APE questioner strategies.

Reproduces the technical evaluation from the paper, comparing:
- **APE** (proposed) — information-theoretic query generation.
- **In-Context** — LLM in-context reasoning.

Datasets:
- **DesignBench** — 30 creative design tasks with reference images (vision-based simulator).
- **IDEA-Bench**  — 29 professional design tasks with ground-truth text prompts (intent-based simulator).

Usage::

    python benchmark.py --dataset DesignBench --questioner APE \\
        --max-iters 15 --num-exp 5 --max-processes 4
"""
import argparse
import multiprocessing as mp
import os
import time

import pandas as pd
from dotenv import load_dotenv

from ape import Project
from ape.logger import create_logger
from ape.utils import LLMAgent, parse_llm_output_to_json, load_prompt

load_dotenv()

PROMPT_FOLDER = None  # uses ape/prompt_templates/ by default
IDEA_BENCH_DESIGN_TYPE_MAP = {
    "arch. style": "Architectural Style Design",
    "bus. card":   "Business Card Design",
    "int.":        "Interior Design",
    "paint.":      "Painting",
    "sclup.":      "Sculpture Design",
    "ticket":      "Ticket Design",
    "land":        "Landmark Building Design",
    "logo":        "Logo Design",
    "poster":      "Poster Design",
}


# ===== DATASET =====

class Dataset:
    """Dataset loader for DesignBench and IDEA-Bench."""

    def __init__(self, name: str, data_folder: str = "../datasets/"):
        self.name = name
        if name == "DesignBench":
            data_folder = os.path.join(data_folder, "designbench/")
            df = pd.read_csv(os.path.join(data_folder, "DesignBench.csv"))
            self.items = [
                {
                    "design_type": row["design_type"],
                    "project_name": row["project_name"],
                    "initial_description": row["initial_description"],
                    "ground_truth": os.path.join(data_folder, row["ground_truth"]),
                    "use_vision": True,
                }
                for _, row in df.iterrows()
            ]
        elif name == "IDEA-Bench":
            data_folder = os.path.join(data_folder, "IDEA-Bench/")
            df = pd.read_csv(os.path.join(data_folder, "task_t2i.csv"))
            self.items = [
                {
                    "design_type": IDEA_BENCH_DESIGN_TYPE_MAP[row["design_type"]],
                    "project_name": row["folder_name"],
                    "initial_description": row["prompt"].split(".")[0],
                    "ground_truth": row["prompt"],
                    "use_vision": False,
                }
                for _, row in df.iterrows()
            ]
        else:
            raise ValueError(f"Unknown dataset: '{name}'. Choose 'DesignBench' or 'IDEA-Bench'.")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


# ===== SIMULATED USERS =====

class User:
    """Text-based simulated user that answers questions from a ground-truth description."""

    def __init__(self, task: str, ground_truth: str, logger,
                 seed: int = None, temperature: float = 0.7):
        self.task = task
        self.ground_truth = ground_truth
        self.logger = logger
        self.seed = seed
        self.temperature = temperature
        self._llm = LLMAgent(provider="openai")
        self.logger.info(
            "User initialized",
            extra={"role": "user", "content": {"task": task, "ground_truth": ground_truth}},
        )

    def get_answer(self, question: str) -> str:
        prompt = load_prompt("user_simulation.md", PROMPT_FOLDER).format(
            task=self.task,
            ground_truth_description=self.ground_truth,
            question=question,
        )
        response = parse_llm_output_to_json(
            self._llm.call(prompt=prompt, temperature=self.temperature, seed=self.seed)["text"]
        )
        self.logger.info("Answer", extra={"role": "user", "content": response})
        return response["Answer"]


class UserVision(User):
    """Vision-based simulated user that answers questions by inspecting a reference image."""

    def get_answer(self, question: str) -> str:
        prompt = load_prompt("user_simulation_with_vision.md", PROMPT_FOLDER).format(
            task=self.task,
            question=question,
        )
        response = parse_llm_output_to_json(
            self._llm.call_with_vision(
                prompt=prompt,
                image_path_or_url=self.ground_truth,
                temperature=self.temperature,
                seed=self.seed,
            )["text"]
        )
        self.logger.info("Answer", extra={"role": "user", "content": response})
        return response["Answer"]


# ===== EXPERIMENT RUNNER =====

def run_single_experiment(args):
    """Run one experiment. Designed for use in a multiprocessing pool."""
    index, item, exp_id, questioner_type, max_iters, N, M, total, seed = args
    name = item["project_name"]
    try:
        print(f"[{index + 1}/{total}] Starting: {name} (ID {exp_id})")
        project = Project(
            task=item["design_type"],
            description=item["initial_description"],
            name=name,
            id=exp_id,
            questioner=questioner_type,
            seed=seed,
            prompt_folder=PROMPT_FOLDER,
        )
        UserClass = UserVision if item["use_vision"] else User
        user = UserClass(
            task=project.task,
            ground_truth=item["ground_truth"],
            logger=project.logger,
            seed=seed + 1,
        )
        for i in range(max_iters):
            print(f"  Iter {i + 1}/{max_iters}: {name} (ID {exp_id})")
            project.ask_questions(N=N, M=M)
            project.answer_question(user)
            project.extract_requirements()
        project.save_final()
        project.save_images()
        print(f"[{index + 1}/{total}] Done: {name} (ID {exp_id})")
        return (index, exp_id, True, None)
    except Exception as exc:
        print(f"[{index + 1}/{total}] Error: {name} (ID {exp_id}): {exc}")
        return (index, exp_id, False, str(exc))


def build_experiment_args(dataset, questioner_type, exp_id_start, num_exp, max_iters, N, M, seeds):
    total = len(dataset)
    return [
        (idx, dataset[idx], exp_id, questioner_type, max_iters, N, M, total, seed)
        for idx in range(total)
        for exp_id, seed in zip(range(exp_id_start, exp_id_start + num_exp), seeds)
    ]


def run_experiments(experiment_args, max_processes, parallel):
    if parallel and len(experiment_args) > 1:
        n_proc = min(max_processes, mp.cpu_count(), len(experiment_args))
        print(f"Running {len(experiment_args)} experiments with {n_proc} processes.")
        try:
            with mp.Pool(processes=n_proc) as pool:
                return pool.map(run_single_experiment, experiment_args)
        except Exception as exc:
            print(f"Multiprocessing failed ({exc}); falling back to sequential.")
    print("Running experiments sequentially.")
    return [run_single_experiment(a) for a in experiment_args]


def print_summary(results, elapsed):
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS SUMMARY")
    print("=" * 60)
    successful = sum(1 for _, _, ok, _ in results if ok)
    for idx, exp_id, ok, error in results:
        mark = "✓" if ok else "✗"
        suffix = f": {error}" if error else ""
        print(f"  {mark} [{idx + 1}] ID {exp_id}{suffix}")
    print(f"\nTotal: {len(results)}  |  Success: {successful}  |  Failed: {len(results) - successful}")
    print(f"Elapsed: {elapsed:.1f}s  |  Avg: {elapsed / len(results):.1f}s/exp")


# ===== CLI =====

def parse_args():
    parser = argparse.ArgumentParser(description="Run APE benchmark experiments.")
    parser.add_argument("--dataset", choices=["DesignBench", "IDEA-Bench"], default="DesignBench")
    parser.add_argument("--questioner",
                        choices=["APE", "In-Context", "Vanilla", "APE-MC"],
                        default="APE",
                        help="Query strategy: APE, In-Context, "
                             "Vanilla, or APE-MC.")
    parser.add_argument("--data-folder", default="../datasets/",
                        help="Root folder containing dataset sub-directories.")
    parser.add_argument("--max-iters", type=int, default=15,
                        help="Q&A iterations per experiment run (paper used 15).")
    parser.add_argument("--num-exp", type=int, default=5,
                        help="Runs per dataset item.")
    parser.add_argument("--exp-id-start", type=int, default=0,
                        help="Starting experiment ID.")
    parser.add_argument("--N", type=int, default=5,
                        help="Candidate questions per iteration.")
    parser.add_argument("--M", type=int, default=5,
                        help="Options per question.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[12, 34, 56, 78, 90])
    parser.add_argument("--max-processes", type=int, default=4)
    parser.add_argument("--no-parallel", action="store_true",
                        help="Disable parallel execution.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    dataset = Dataset(name=args.dataset, data_folder=args.data_folder)
    print(f"Dataset: {args.dataset} ({len(dataset)} items)")
    print(f"Questioner: {args.questioner}")

    experiment_args = build_experiment_args(
        dataset=dataset,
        questioner_type=args.questioner,
        exp_id_start=args.exp_id_start,
        num_exp=args.num_exp,
        max_iters=args.max_iters,
        N=args.N,
        M=args.M,
        seeds=args.seeds,
    )
    print(f"Total experiments: {len(experiment_args)}")
    print("=" * 60)

    start = time.time()
    results = run_experiments(experiment_args, args.max_processes, not args.no_parallel)
    print_summary(results, time.time() - start)
