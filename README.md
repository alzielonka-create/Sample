# addressdb

A small address database: SQLite storage, a Python API, and a command-line tool.
It uses only the Python standard library (3.9+), so there's nothing to install.

## CLI

```bash
python -m addressdb add --first Ada --last Lovelace --street "12 St James's Sq" \
    --zip "SW1Y 4JH" --city London --country UK --email ada@example.com --tags work,friends
python -m addressdb add --company "Acme GmbH" --city Berlin --zip 10115 --country DE

python -m addressdb list                         # all, sorted by name
python -m addressdb list --tag work --sort city  # filters: --tag --city --country --limit
python -m addressdb search "ada london"          # every term must match some field
python -m addressdb search acme --json           # machine-readable output
python -m addressdb show 1                       # mailing-label view plus details
python -m addressdb update 1 --city Paris
python -m addressdb delete 1                     # asks for confirmation; -y to skip
python -m addressdb export backup.csv            # .csv or .json, chosen by extension
python -m addressdb import backup.json           # invalid rows are skipped and reported
python -m addressdb duplicates                   # same name + street + postal code
```

The database file defaults to `./addresses.db`. Override it with `--db PATH` or the `ADDRESSDB_PATH` environment variable.

## Python API

```python
from addressdb import AddressDB, Address

with AddressDB("addresses.db") as db:
    a = db.add(Address(first_name="Ada", last_name="Lovelace", city="London"))
    db.update(a.id, email="ada@example.com")
    for hit in db.search("lovelace", tag="work"):
        print(hit.formatted())
```

## Data model

Fields: `first_name`, `last_name`, `company`, `street`, `street2`, `city`, `state`, `postal_code`, `country`, `phone`, `email`, `tags` (comma-separated and lowercased), `notes`, plus `id`, `created_at`, and `updated_at`.

Rules: a record needs a first name, last name, or company. An email address, if given, must look like one.

## Tests

```bash
python -m unittest discover -s tests -t .
```
