# addressdb

A small address database: a web app, a command-line tool, and a Python API, all sharing one SQLite file.

## Web app

```bash
pip install -r requirements.txt     # Flask; the CLI and Python API need nothing extra
python -m addressdb.web             # then open http://127.0.0.1:5000
python -m addressdb.web --db ~/my-addresses.db --port 8000
```

You can list, search, filter by tag, sort, add, edit, and delete addresses (deleting asks first), import CSV or JSON by upload, export CSV or JSON as a download, and find duplicates. It works on phones (each address becomes a card) and follows the system dark mode.

**Security: there is no login.** The server listens only on `127.0.0.1` (this computer) by default. Don't run it with `--host 0.0.0.0` on a network you don't fully trust, because anyone who can reach it can read and delete everything. Forms are protected against cross-site request forgery, all output is HTML-escaped, and a strict Content-Security-Policy is set. Flask's built-in server is for one person's use, not for production hosting.

## Command line

The command line uses only the Python standard library (3.9+).


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
