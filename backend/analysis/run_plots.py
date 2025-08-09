from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv('.env')
import argparse
import importlib
import inspect
from pathlib import Path
from typing import Sequence

import matplotlib
import matplotlib.pyplot as plt

from .context import AnalysisContext
from .registry import get_registered


def _ensure_output_dir(path: str) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _save_figures(figures: Sequence[plt.Figure], base_name: str, output_dir: Path, fmt: str = "png") -> None:
    for idx, fig in enumerate(figures, start=1):
        suffix = f"_{idx}" if len(figures) > 1 else ""
        file_path = output_dir / f"{base_name}{suffix}.{fmt}"
        fig.tight_layout()
        fig.savefig(file_path, format=fmt, dpi=200)


def run(
    module: str,
    output_dir: str,
    fmt: str = "png",
    show: bool = True,
    save: bool = False,
    only: Sequence[str] | None = None,
) -> None:
    # Configure interactive backend only when showing
    if show:
        # Prefer TkAgg if available; fallback to default
        try:
            matplotlib.use("TkAgg", force=True)
        except Exception:
            pass
    # Import the user-provided module to register its plot functions
    importlib.import_module(module)

    registry = get_registered()
    if only:
        registry = {k: v for k, v in registry.items() if k in set(only)}

    if not registry:
        raise SystemExit("No registered plot functions found. Use @register_plot decorator.")

    ctx = AnalysisContext()
    out_dir: Path | None = None
    should_save = save
    if should_save:
        out_dir = _ensure_output_dir(output_dir)

    generated: list[tuple[str, list[plt.Figure]]] = []

    for name, func in registry.items():
        # Call function with context if it expects one
        try:
            if len(inspect.signature(func).parameters) == 0:
                result = func()
            else:
                result = func(ctx)
        except Exception as exc:
            print(f"[ERROR] Plot function '{name}' failed: {exc}")
            continue

        if result is None:
            continue

        # Normalize to a list of figures
        figures: list[plt.Figure]
        if isinstance(result, plt.Figure):
            figures = [result]
        else:
            figures = list(result)

        generated.append((name, figures))

    if show:
        # Show all generated figures together
        plt.show(block=True)
    if should_save and out_dir is not None:
        for name, figures in generated:
            _save_figures(figures, base_name=name, output_dir=out_dir, fmt=fmt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run registered analysis plot functions and show/save outputs.")
    parser.add_argument("--module", required=True, help="Python module path to import (contains @register_plot functions)")
    parser.add_argument("--output-dir", default="analysis/output", help="Directory to store generated figures")
    parser.add_argument("--format", default="png", choices=["png", "pdf", "svg"], help="Output image format")
    parser.add_argument("--no-show", action="store_true", help="Disable displaying figures (default is to show)")
    parser.add_argument("--save", action="store_true", help="Save figures (only when --no-show is also provided)")
    parser.add_argument("--only", nargs="*", help="Subset of plot function names to run")
    args = parser.parse_args()

    show = not args.no_show
    run(module=args.module, output_dir=args.output_dir, fmt=args.format, show=show, save=bool(args.save), only=args.only)


if __name__ == "__main__":
    main()


