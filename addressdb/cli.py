"""Command-line interface: python -m addressdb <command> ..."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .db import Address, AddressDB, ValidationError

DEFAULT_DB = os.environ.get("ADDRESSDB_PATH", "addresses.db")

FIELD_FLAGS = {
    "first_name": ("--first", "-f"),
    "last_name": ("--last", "-l"),
    "company": ("--company", "-c"),
    "street": ("--street",),
    "street2": ("--street2",),
    "city": ("--city",),
    "state": ("--state",),
    "postal_code": ("--zip", "--postal-code"),
    "country": ("--country",),
    "phone": ("--phone",),
    "email": ("--email",),
    "tags": ("--tags",),
    "notes": ("--notes",),
}


def _add_field_args(p: argparse.ArgumentParser) -> None:
    for dest, flags in FIELD_FLAGS.items():
        p.add_argument(*flags, dest=dest, default=None)


def _collect_fields(args: argparse.Namespace) -> dict:
    return {k: getattr(args, k) for k in FIELD_FLAGS if getattr(args, k) is not None}


def _print_table(rows: list[Address]) -> None:
    if not rows:
        print("No addresses found.")
        return
    cols = [("ID", lambda a: str(a.id)),
            ("Name", lambda a: a.display_name),
            ("Street", lambda a: a.street),
            ("Postal", lambda a: a.postal_code),
            ("City", lambda a: a.city),
            ("Country", lambda a: a.country),
            ("Email", lambda a: a.email),
            ("Tags", lambda a: a.tags)]
    data = [[fn(r) for _, fn in cols] for r in rows]
    widths = [min(max(len(h), *(len(d[i]) for d in data)), 32) for i, (h, _) in enumerate(cols)]

    def fmt(cells):
        return "  ".join((c[: w - 1] + "…" if len(c) > w else c).ljust(w)
                         for c, w in zip(cells, widths)).rstrip()

    print(fmt([h for h, _ in cols]))
    print("  ".join("-" * w for w in widths))
    for d in data:
        print(fmt(d))
    print(f"\n{len(rows)} address(es)")


def _print_detail(a: Address) -> None:
    print(a.formatted())
    print()
    for label, value in (("ID", a.id), ("Phone", a.phone), ("Email", a.email),
                         ("Tags", a.tags), ("Notes", a.notes),
                         ("Created", a.created_at), ("Updated", a.updated_at)):
        if value not in ("", None):
            print(f"{label + ':':9}{value}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="addressdb", description="A small SQLite-backed address database.")
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"database file (default: {DEFAULT_DB}; env ADDRESSDB_PATH)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("add", help="add an address")
    _add_field_args(s)

    s = sub.add_parser("show", help="show one address")
    s.add_argument("id", type=int)

    s = sub.add_parser("update", help="change fields of an address")
    s.add_argument("id", type=int)
    _add_field_args(s)

    s = sub.add_parser("delete", help="delete an address")
    s.add_argument("id", type=int)
    s.add_argument("-y", "--yes", action="store_true", help="skip confirmation")

    for name, helptext in (("list", "list addresses"), ("search", "search all fields")):
        s = sub.add_parser(name, help=helptext)
        if name == "search":
            s.add_argument("text", help="search terms (all must match)")
        s.add_argument("--tag")
        s.add_argument("--city")
        s.add_argument("--country")
        s.add_argument("--sort", default="name",
                       choices=["name", "city", "postal_code", "created", "updated", "id"])
        s.add_argument("--limit", type=int)
        s.add_argument("--json", action="store_true", help="output JSON")

    s = sub.add_parser("export", help="export to CSV or JSON (by file extension)")
    s.add_argument("path")

    s = sub.add_parser("import", help="import from CSV or JSON (by file extension)")
    s.add_argument("path")

    sub.add_parser("duplicates", help="find likely duplicate records")
    sub.add_parser("stats", help="show record count")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with AddressDB(args.db) as db:
            return _dispatch(db, args)
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyError, FileNotFoundError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1


def _dispatch(db: AddressDB, args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "add":
        a = db.add(Address(**_collect_fields(args)))
        print(f"Added address {a.id}: {a.display_name}")
    elif cmd == "show":
        a = db.get(args.id)
        if a is None:
            raise KeyError(f"no address with id {args.id}")
        _print_detail(a)
    elif cmd == "update":
        changes = _collect_fields(args)
        if not changes:
            raise ValidationError("nothing to update; pass at least one field flag")
        a = db.update(args.id, **changes)
        print(f"Updated address {a.id}: {a.display_name}")
    elif cmd == "delete":
        a = db.get(args.id)
        if a is None:
            raise KeyError(f"no address with id {args.id}")
        if not args.yes:
            reply = input(f"Delete {a.id}: {a.display_name}? [y/N] ")
            if reply.strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return 0
        db.delete(args.id)
        print(f"Deleted address {args.id}")
    elif cmd in ("list", "search"):
        text = getattr(args, "text", None)
        rows = db.search(text, tag=args.tag, city=args.city, country=args.country,
                         order_by=args.sort, limit=args.limit)
        if args.json:
            print(json.dumps([r.to_dict() for r in rows], indent=2, ensure_ascii=False))
        else:
            _print_table(rows)
    elif cmd == "export":
        n = (db.export_json if args.path.lower().endswith(".json") else db.export_csv)(args.path)
        print(f"Exported {n} address(es) to {args.path}")
    elif cmd == "import":
        fn = db.import_json if args.path.lower().endswith(".json") else db.import_csv
        n, errors = fn(args.path)
        for e in errors:
            print(f"skipped {e}", file=sys.stderr)
        print(f"Imported {n} address(es) from {args.path}")
        return 1 if errors and n == 0 else 0
    elif cmd == "duplicates":
        groups = db.find_duplicates()
        if not groups:
            print("No duplicates found.")
        for g in groups:
            print("Possible duplicates: " + ", ".join(f"{a.id} ({a.display_name})" for a in g))
    elif cmd == "stats":
        print(f"{db.count()} address(es) in {db.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
