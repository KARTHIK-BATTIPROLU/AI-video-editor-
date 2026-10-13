"""CLI entrypoint + human-in-the-loop runner (MASTER_PROMPT §7-§8).

    python -m pipeline.run --video in.mp4 --template punch --out out.mp4 --thread job-001

Runs the graph until the render interrupt, prints the planned placement, asks for
approval, then resumes through render->finalize. Re-running with the same --thread
resumes from the last checkpoint instead of recomputing finished stages.
"""

import argparse
import os
import sys

from .graph import build_graph
from .templates import TEMPLATES
from .nodes._coerce import as_page


def _print_pages(pages) -> None:
    print("\n=== Planned caption placement ===")
    if not pages:
        print("  (no pages)")
    for i, p in enumerate(pages):
        page = as_page(p)
        text = " ".join(w.text for w in page.words)
        print(
            f"[{i:02d}] {page.start_ms / 1000:6.2f}-{page.end_ms / 1000:6.2f}s  "
            f"pos=({page.x:.2f},{page.y:.2f}) anchor={page.anchor:<6}  {text}"
        )
    print("=================================\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reference-style auto-caption pipeline")
    ap.add_argument("--video", required=True, help="input video path")
    ap.add_argument("--template", required=True, choices=list(TEMPLATES),
                    help="caption style")
    ap.add_argument("--out", required=True, help="output mp4 path")
    ap.add_argument("--thread", required=True, help="checkpoint thread id (resume key)")
    ap.add_argument("--language", default="en", help="transcription language hint")
    ap.add_argument("--yes", action="store_true",
                    help="auto-approve placement (skip the y/n prompt)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.video):
        print(f"error: video not found: {args.video}", file=sys.stderr)
        return 2

    app = build_graph()
    config = {"configurable": {"thread_id": args.thread}}

    initial = {
        "video_path": os.path.abspath(args.video),
        "template_id": args.template,
        "output_path": os.path.abspath(args.out),
        "language": args.language,
        "status": "running",
    }

    # ---- run up to the render interrupt (resuming if the thread already exists)
    snapshot = app.get_state(config)
    if not snapshot.values:
        print(f"[run] starting fresh thread '{args.thread}'")
        app.invoke(initial, config)
    else:
        print(f"[run] resuming thread '{args.thread}' (next={snapshot.next or 'gate'})")
        if snapshot.next and snapshot.next != ("render",):
            app.invoke(None, config)  # finish pending work up to the gate

    snapshot = app.get_state(config)
    values = snapshot.values
    status = values.get("status")
    pages = values.get("pages") or []

    # ---- graceful abort: empty transcript (nothing to caption)
    # The conditional edge routes transcribe->finalize, but the barrier layout
    # still runs via its other predecessors; the tail nodes mark this failed and
    # render nothing. Detect it here and stop before the render gate.
    if status == "failed" or not pages:
        print(f"[run] nothing to caption (status={status}); not rendering.")
        if values.get("errors"):
            print("      errors:", values["errors"])
        return 1

    # ---- already fully rendered on a prior run
    if snapshot.next == () and status == "done":
        print(f"[run] already done -> {values.get('rendered_path')}")
        return 0

    # ---- gate: show placement and ask for approval (§5 interrupt_before render)
    _print_pages(pages)

    if args.yes:
        approve = True
        print("Auto-approving (--yes).")
    else:
        approve = input("Approve and render? [y/n] ").strip().lower() == "y"

    if not approve:
        print("Not rendering. Checkpoint left intact; "
              f"re-run with --thread {args.thread} to resume.")
        return 0

    # ---- resume through render -> finalize
    final = app.invoke(None, config)
    print(f"[run] status={final.get('status')} -> {final.get('rendered_path')}")
    return 0 if final.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
