"""All MLX work (model load + inference) runs on ONE dedicated thread.

MLX streams are thread-affine: a model loaded on one thread errors ('no Stream in current thread') if used
from another. Push-to-talk, typed input, and Claude-fallback all call the models from different threads, so
every MLX call is marshaled here to a single worker thread.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sheru-mlx")


def run(fn, *args, **kwargs):
    """Run fn on the dedicated MLX thread and block for the result."""
    return _EXEC.submit(fn, *args, **kwargs).result()
