"""SQLite storage layer for the address database."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS addresses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name   TEXT NOT NULL DEFAULT '',
    last_name    TEXT NOT NULL DEFAULT '',
    company      TEXT NOT NULL DEFAULT '',
    street       TEXT NOT NULL DEFAULT '',
    street2      TEXT NOT NULL DEFAULT '',
    city         TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT '',
    postal_code  TEXT NOT NULL DEFAULT '',
    country      TEXT NOT NULL DEFAULT '',
    phone        TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    CHECK (first_name <> '' OR last_name <> '' OR company <> '')
);
CREATE INDEX IF NOT EXISTS idx_addresses_name ON addresses (last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_addresses_city ON addresses (city);
CREATE INDEX IF NOT EXISTS idx_addresses_postal ON addresses (postal_code);
CREATE INDEX IF NOT EXISTS idx_addresses_email ON addresses (email);
"""

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(ValueError):
    """Raised when an address record fails validation."""


@dataclass
class Address:
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    street: str = ""
    street2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    tags: str = ""  # comma-separated
    notes: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    EDITABLE = (
        "first_name", "last_name", "company", "street", "street2", "city",
        "state", "postal_code", "country", "phone", "email", "tags", "notes",
    )

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        if name and self.company:
            return f"{name} ({self.company})"
        return name or self.company

    @property
    def tag_list(self) -> list[str]:
        return [t for t in (s.strip() for s in self.tags.split(",")) if t]

    def formatted(self) -> str:
        """Multi-line mailing-label style rendering."""
        lines = [self.display_name]
        if self.street:
            lines.append(self.street)
        if self.street2:
            lines.append(self.street2)
        locality = " ".join(p for p in (self.postal_code, self.city) if p)
        if self.state:
            locality = f"{locality}, {self.state}" if locality else self.state
        if locality:
            lines.append(locality)
        if self.country:
            lines.append(self.country)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_tags(tags: str) -> str:
    seen: list[str] = []
    for t in tags.split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def validate(addr: Address) -> Address:
    for name in Address.EDITABLE:
        value = getattr(addr, name)
        if value is None:
            value = ""
        if not isinstance(value, str):
            value = str(value)
        setattr(addr, name, value.strip())
    if not (addr.first_name or addr.last_name or addr.company):
        raise ValidationError("an address needs a first name, last name, or company")
    if addr.email and not EMAIL_RE.match(addr.email):
        raise ValidationError(f"invalid email address: {addr.email!r}")
    addr.tags = _normalize_tags(addr.tags)
    return addr


class AddressDB:
    def __init__(self, path: str | Path = "addresses.db"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    # -- context manager -------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "AddressDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _row_to_address(row: sqlite3.Row) -> Address:
        return Address(**{k: row[k] for k in row.keys()})

    # -- CRUD ------------------------------------------------------------
    def add(self, addr: Address) -> Address:
        addr = validate(addr)
        ts = _now()
        cols = list(Address.EDITABLE) + ["created_at", "updated_at"]
        values = [getattr(addr, c) for c in Address.EDITABLE] + [ts, ts]
        cur = self.conn.execute(
            f"INSERT INTO addresses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            values,
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, address_id: int) -> Optional[Address]:
        row = self.conn.execute(
            "SELECT * FROM addresses WHERE id = ?", (address_id,)
        ).fetchone()
        return self._row_to_address(row) if row else None

    def update(self, address_id: int, **changes) -> Address:
        current = self.get(address_id)
        if current is None:
            raise KeyError(f"no address with id {address_id}")
        unknown = set(changes) - set(Address.EDITABLE)
        if unknown:
            raise ValidationError(f"unknown field(s): {', '.join(sorted(unknown))}")
        for k, v in changes.items():
            setattr(current, k, v)
        current = validate(current)
        assignments = ", ".join(f"{c} = ?" for c in Address.EDITABLE)
        self.conn.execute(
            f"UPDATE addresses SET {assignments}, updated_at = ? WHERE id = ?",
            [getattr(current, c) for c in Address.EDITABLE] + [_now(), address_id],
        )
        self.conn.commit()
        return self.get(address_id)

    def delete(self, address_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM addresses WHERE id = ?", (address_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # -- queries ---------------------------------------------------------
    def list(
        self,
        *,
        tag: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        order_by: str = "name",
        limit: Optional[int] = None,
    ) -> list[Address]:
        return self.search(None, tag=tag, city=city, country=country,
                           order_by=order_by, limit=limit)

    def search(
        self,
        text: Optional[str],
        *,
        tag: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        order_by: str = "name",
        limit: Optional[int] = None,
    ) -> list[Address]:
        """Case-insensitive substring search across all text fields."""
        where: list[str] = []
        params: list = []
        if text:
            # Every whitespace-separated term must match somewhere.
            for term in text.split():
                like = f"%{term}%"
                clause = " OR ".join(f"{c} LIKE ?" for c in Address.EDITABLE)
                where.append(f"({clause})")
                params.extend([like] * len(Address.EDITABLE))
        if tag:
            where.append("(',' || tags || ',') LIKE ?")
            params.append(f"%,{tag.strip().lower()},%")
        if city:
            where.append("city LIKE ?")
            params.append(city)
        if country:
            where.append("country LIKE ?")
            params.append(country)

        orders = {
            "name": "COALESCE(NULLIF(last_name, ''), company) COLLATE NOCASE, first_name COLLATE NOCASE",
            "city": "city COLLATE NOCASE, last_name COLLATE NOCASE",
            "postal_code": "postal_code, last_name COLLATE NOCASE",
            "created": "created_at, id",
            "updated": "updated_at DESC, id",
            "id": "id",
        }
        if order_by not in orders:
            raise ValidationError(f"order_by must be one of: {', '.join(orders)}")

        sql = "SELECT * FROM addresses"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {orders[order_by]}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._row_to_address(r) for r in self.conn.execute(sql, params)]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM addresses").fetchone()[0]

    def find_duplicates(self) -> list[list[Address]]:
        """Groups of records that share name + street + postal code (case-insensitive)."""
        rows = self.conn.execute(
            """
            SELECT group_concat(id) AS ids FROM addresses
            GROUP BY lower(first_name), lower(last_name), lower(company),
                     lower(street), lower(postal_code)
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        return [[self.get(int(i)) for i in r["ids"].split(",")] for r in rows]

    # -- import / export -------------------------------------------------
    def export_csv(self, path: str | Path) -> int:
        records = self.list(order_by="id")
        names = [f.name for f in fields(Address)]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=names)
            writer.writeheader()
            for r in records:
                writer.writerow(r.to_dict())
        return len(records)

    def export_json(self, path: str | Path) -> int:
        records = [r.to_dict() for r in self.list(order_by="id")]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        return len(records)

    def import_records(self, records: Iterable[dict]) -> tuple[int, list[str]]:
        """Insert records; returns (imported_count, error_messages).

        The whole import runs in one transaction; invalid rows are skipped
        and reported rather than aborting the import.
        """
        imported, errors = 0, []
        ts = _now()
        cols = list(Address.EDITABLE) + ["created_at", "updated_at"]
        sql = f"INSERT INTO addresses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self.conn:
            for n, rec in enumerate(records, start=1):
                try:
                    addr = validate(Address(**{k: rec.get(k, "") or "" for k in Address.EDITABLE}))
                except ValidationError as e:
                    errors.append(f"record {n}: {e}")
                    continue
                self.conn.execute(sql, [getattr(addr, c) for c in Address.EDITABLE] + [ts, ts])
                imported += 1
        return imported, errors

    def import_csv(self, path: str | Path) -> tuple[int, list[str]]:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return self.import_records(csv.DictReader(fh))

    def import_json(self, path: str | Path) -> tuple[int, list[str]]:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValidationError("JSON import must be a list of objects")
        return self.import_records(data)
