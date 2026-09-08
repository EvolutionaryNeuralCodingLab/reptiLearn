"""CLI for standalone turtle Re-ID."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reid.gallery import DEFAULT_GALLERY_DIR, DEFAULT_THRESHOLD, TurtleGallery

EXIT_UNKNOWN = 0
EXIT_MATCH = 1
EXIT_ERROR = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reid",
        description=(
            "Standalone turtle re-identification with MiewID. "
            "Use tight shell/body crops (not full arena scenes) for best results."
        ),
    )
    parser.add_argument(
        "--gallery-dir",
        type=Path,
        default=DEFAULT_GALLERY_DIR,
        help=f"Gallery root directory (default: {DEFAULT_GALLERY_DIR})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    enroll = sub.add_parser(
        "enroll",
        help="Enroll a turtle from one or more images",
    )
    enroll.add_argument("--id", required=True, dest="turtle_id", help="Turtle ID")
    enroll.add_argument(
        "--images",
        nargs="+",
        required=True,
        type=Path,
        help="Image paths (tight crops recommended)",
    )
    enroll.add_argument(
        "--add-images",
        action="store_true",
        help="Append chips to an existing turtle ID",
    )
    enroll.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing turtle ID (delete prior chips, then enroll)",
    )

    identify = sub.add_parser(
        "identify",
        help="Match a probe image against the gallery",
    )
    identify.add_argument(
        "--image",
        required=True,
        type=Path,
        help="Probe image path (tight crop recommended)",
    )
    identify.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Cosine similarity threshold (default: {DEFAULT_THRESHOLD})",
    )
    identify.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of nearest gallery chips to report (default: 5)",
    )

    sub.add_parser("list", help="List enrolled turtles")

    mark = sub.add_parser(
        "mark-used",
        help="Mark a turtle as already used in experiments",
    )
    mark.add_argument("--id", required=True, dest="turtle_id", help="Turtle ID")
    mark.add_argument(
        "--note",
        default="",
        help="Optional note (e.g. session name / date)",
    )

    remove = sub.add_parser("remove", help="Remove a turtle from the gallery")
    remove.add_argument("--id", required=True, dest="turtle_id", help="Turtle ID")

    return parser


def _cmd_enroll(gallery: TurtleGallery, args: argparse.Namespace) -> int:
    turtle = gallery.enroll(
        args.turtle_id,
        args.images,
        add_images=args.add_images,
        force=args.force,
    )
    n = len(turtle.get("images", []))
    action = "Updated" if args.add_images else "Enrolled"
    print(f"{action} turtle '{args.turtle_id}' ({n} image(s) on disk).")
    return EXIT_UNKNOWN


def _cmd_identify(gallery: TurtleGallery, args: argparse.Namespace) -> int:
    result = gallery.identify(
        args.image,
        top_k=args.top_k,
        threshold=args.threshold,
    )
    if result.best is None:
        print("UNKNOWN (gallery is empty)")
        return EXIT_UNKNOWN

    print("Top matches:")
    for i, hit in enumerate(result.hits, start=1):
        print(
            f"  {i}. {hit.turtle_id}  sim={hit.similarity:.4f}  chip={hit.image_path}"
        )

    if result.matched_id is not None:
        print(
            f"MATCH {result.matched_id} "
            f"(sim={result.best.similarity:.4f}, threshold={args.threshold})"
        )
        return EXIT_MATCH

    print(
        f"UNKNOWN "
        f"(best={result.best.turtle_id} sim={result.best.similarity:.4f}, "
        f"threshold={args.threshold})"
    )
    return EXIT_UNKNOWN


def _cmd_list(gallery: TurtleGallery, _args: argparse.Namespace) -> int:
    rows = gallery.list_turtles()
    if not rows:
        print("Gallery is empty.")
        return EXIT_UNKNOWN
    for row in rows:
        used = "used" if row["used"] else "unused"
        print(
            f"{row['id']}\tchips={row['chip_count']}\t{used}\t"
            f"updated={row.get('updated_at') or '-'}"
        )
        for note in row.get("used_notes") or []:
            print(f"  note @ {note.get('at')}: {note.get('note')}")
    return EXIT_UNKNOWN


def _cmd_mark_used(gallery: TurtleGallery, args: argparse.Namespace) -> int:
    gallery.mark_used(args.turtle_id, note=args.note)
    print(f"Marked '{args.turtle_id}' as used.")
    return EXIT_UNKNOWN


def _cmd_remove(gallery: TurtleGallery, args: argparse.Namespace) -> int:
    gallery.remove(args.turtle_id)
    print(f"Removed '{args.turtle_id}'.")
    return EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        gallery = TurtleGallery(gallery_dir=args.gallery_dir)
        if args.command == "enroll":
            return _cmd_enroll(gallery, args)
        if args.command == "identify":
            return _cmd_identify(gallery, args)
        if args.command == "list":
            return _cmd_list(gallery, args)
        if args.command == "mark-used":
            return _cmd_mark_used(gallery, args)
        if args.command == "remove":
            return _cmd_remove(gallery, args)
        parser.error(f"Unknown command: {args.command}")
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
