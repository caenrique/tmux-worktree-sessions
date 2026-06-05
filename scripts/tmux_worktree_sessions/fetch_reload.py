"""Background fetch + fzf reload helper.

Invoked by the branch picker via fzf's ``execute-silent`` binding. Runs
``git fetch`` while a spinner thread posts ``change-header`` updates to
fzf's listen port; once the fetch completes, regenerates the picker
entries file and posts a final ``change-header(...)+reload(cat ...)``
so fzf swaps in the fresh list.

Every input is an explicit parameter — no ``os.environ`` or
``time.time()`` reads. Fork/detach lives in the CLI handler.

Why curl, not ``urllib.request``: ``curl`` is already a documented
runtime dep of the plugin and the test stub captures every POST
verbatim, so the wire output is exercised end-to-end without any
HTTP-level mocking.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
from pathlib import Path

from .picker import IconSet, gen_branch_picker_entries

_SPIN_FRAMES: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPIN_INITIAL_DELAY_S: float = 0.3
_SPIN_INTERVAL_S: float = 0.12


def _curl_post(port: int, body: str, *, max_time: float) -> None:
    """POST ``body`` to fzf's ``--listen`` port, swallowing all errors.

    Failures are intentionally silent so a missed spinner frame or a
    torn-down listener never bubbles up to the picker.
    """
    subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            str(max_time),
            "-XPOST",
            f"localhost:{port}",
            "-d",
            body,
        ],
        check=False,
        capture_output=True,
    )


def _spinner_loop(stop: threading.Event, *, port: int, header_base: str) -> None:
    """Post a rotating spinner frame until ``stop`` is set.

    The initial 0.3s delay gives fzf time to bind its listener before
    the first POST. ``stop.wait`` returns ``True`` when the event
    fires, which we use as both an abort signal and the inter-frame
    sleep.
    """
    if stop.wait(_SPIN_INITIAL_DELAY_S):
        return
    i = 0
    while not stop.is_set():
        frame = _SPIN_FRAMES[i % len(_SPIN_FRAMES)]
        _curl_post(
            port,
            f"change-header({header_base} {frame} fetching...)",
            max_time=0.5,
        )
        if stop.wait(_SPIN_INTERVAL_S):
            return
        i += 1


def fetch_and_reload(
    repo: Path,
    tmpfile: Path,
    port: int,
    header_base: str,
    *,
    icons: IconSet,
    home: str = "",
    strip_prefixes: list[str] | None = None,
    session_paths: frozenset[Path] = frozenset(),
) -> None:
    """Run ``git fetch``, regenerate ``tmpfile``, and tell fzf to reload.

    Spawns a spinner thread that posts ``change-header`` frames to
    ``port`` while ``git fetch --all --quiet`` runs against ``repo``.
    Branch entries are then rewritten via :func:`gen_branch_picker_entries`
    and a final ``change-header(<base>)+reload(cat <tmpfile>)`` POST
    swaps the fresh list into fzf. A failed fetch is non-fatal — the
    final reload still fires so the picker reflects the local state.
    """
    stop = threading.Event()
    spinner = threading.Thread(
        target=_spinner_loop,
        kwargs={"stop": stop, "port": port, "header_base": header_base},
        daemon=True,
    )
    spinner.start()
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--all", "--quiet"],
            check=False,
            capture_output=True,
        )
        with tmpfile.open("w") as f:
            for line in gen_branch_picker_entries(
                repo,
                icons=icons,
                home=home,
                strip_prefixes=strip_prefixes,
                session_paths=session_paths,
            ):
                f.write(line + "\n")
    finally:
        stop.set()
        spinner.join()

    quoted = shlex.quote(str(tmpfile))
    _curl_post(
        port,
        f"change-header({header_base})+reload(cat {quoted})",
        max_time=2.0,
    )
