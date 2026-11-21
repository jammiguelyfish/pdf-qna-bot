"""PDF ingestion CLI.

Makes the vector index match the PDFs in data/pdfs/, doing only the work that
is needed: new files are added, edited files replace their old chunks, deleted
files are removed, identical copies are skipped, and a run that was interrupted
simply picks up where it stopped. See ingestion.py for how.
"""
import argparse
import os
import sys

from ingestion import sync_directory
from store import open_store

PDF_DIR = "./data/pdfs"
CHROMA_DIR = "./chroma_db"


def print_report(report) -> None:
    def show(label, names):
        if names:
            print(f"  {label}: {', '.join(names)}")

    show("added", report.added)
    show("updated (new content, old chunks replaced)", report.updated)
    show("re-indexed (was incomplete or used another model)", report.reindexed)
    show("removed (no longer in the folder)", report.removed)
    show("unchanged", report.unchanged)
    for name, same_as in report.duplicates:
        print(f"  skipped duplicate: {name} has the same content as {same_as}")
    for name, reason in report.failed:
        print(f"  FAILED: {name}: {reason}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Index PDFs for the Q&A bot")
    parser.add_argument("--pdf-dir", default=PDF_DIR)
    parser.add_argument("--db-dir", default=CHROMA_DIR)
    args = parser.parse_args(argv)

    if not os.path.isdir(args.pdf_dir):
        print(f"Error: PDF directory '{args.pdf_dir}' does not exist.")
        return 1
    if not any(f.lower().endswith(".pdf") for f in os.listdir(args.pdf_dir)):
        print(f"No PDF files found in '{args.pdf_dir}'. Please add PDFs first.")
        return 1

    print("Loading embedding model and opening the index...")
    store = open_store(args.db_dir)
    print(f"Syncing '{args.pdf_dir}' with '{args.db_dir}'...\n")
    report = sync_directory(store, args.pdf_dir)
    print_report(report)

    chunks = len(store.get()["ids"])
    print(f"\nDone. The index holds {chunks} searchable chunks.")
    if not report.ok:
        print(f"{len(report.failed)} file(s) failed; fix them and run again.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
