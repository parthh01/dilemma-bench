from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Union

from matplotlib.figure import Figure


# Global registry of analysis callables
_PLOT_FUNCTIONS: Dict[str, Callable[..., Union[Figure, Sequence[Figure]]]] = {}


def register_plot(func: Callable[..., Union[Figure, Sequence[Figure]]]) -> Callable[..., Union[Figure, Sequence[Figure]]]:
    """Decorator to register a plotting function.

    A plotting function should accept a single argument (context) or no args,
    and it should return either a single matplotlib Figure or a sequence of Figures.
    The function name is used as the registry key.
    """
    name = func.__name__
    if name in _PLOT_FUNCTIONS:
        raise ValueError(f"Plot function '{name}' already registered")
    _PLOT_FUNCTIONS[name] = func
    return func


def list_registered() -> List[str]:
    return sorted(_PLOT_FUNCTIONS.keys())


def get_registered() -> Dict[str, Callable[..., Union[Figure, Sequence[Figure]]]]:
    return dict(_PLOT_FUNCTIONS)


