"""SQLite helpers, schemas and seed data for the mock company."""
import pathlib
import shutil
import sqlite3

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"

SCHEMAS = {
    "expense": """
        CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY AUTOINCREMENT, employee TEXT, trip TEXT, category TEXT,
            amount_inr REAL, cost_center TEXT, project_code TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INTEGER, filename TEXT, sha256 TEXT);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT, vendor TEXT,
            amount_inr REAL, posted_at TEXT);""",
    "hr": """
        CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY AUTOINCREMENT, emp_code TEXT UNIQUE, name TEXT, email TEXT UNIQUE,
            department TEXT, cost_center TEXT, manager TEXT, start_date TEXT, status TEXT DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY AUTOINCREMENT, emp_code TEXT, system TEXT, username TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(emp_code, system));""",
    "ticketing": """
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, category TEXT, requester TEXT,
            assignee TEXT, status TEXT DEFAULT 'open', body TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);""",
}

EMPLOYEES = [
    ("EMP-1001", "Anita Desai", "anita.desai@example.test", "Finance", "CC-4410", "", "2019-04-01"),
    ("EMP-1007", "Priya Sharma", "priya.sharma@example.test", "Sales", "CC-4410", "Anita Desai", "2021-08-16"),
    ("EMP-1012", "Rahul Verma", "rahul.verma@example.test", "Operations", "CC-3320", "Anita Desai", "2020-01-06"),
    ("EMP-1015", "Rahul Mehta", "rahul.mehta@example.test", "Engineering", "CC-5101", "Anita Desai", "2022-03-21"),
]

# invoices_march.xlsx (see make_data.py) differs from this ledger on purpose:
#   INV-2026-0304 amount mismatch, INV-2026-0306 missing, INV-2026-0399 extra
LEDGER = [
    ("INV-2026-0301", "Acme Supplies", 12000, "2026-03-04"), ("INV-2026-0302", "Acme Supplies", 8500, "2026-03-06"),
    ("INV-2026-0303", "BlueSky Logistics", 23400, "2026-03-09"), ("INV-2026-0304", "BlueSky Logistics", 15570, "2026-03-12"),
    ("INV-2026-0305", "Cedar Stationery", 3200, "2026-03-14"), ("INV-2026-0307", "Evergreen Facilities", 18900, "2026-03-20"),
    ("INV-2026-0308", "Evergreen Facilities", 7600, "2026-03-27"), ("INV-2026-0399", "Zenith Consulting", 40000, "2026-03-30"),
]
INVOICES = [  # (invoice_no, vendor, amount_inr, invoice_date)
    ("INV-2026-0301", "Acme Supplies", 12000, "2026-03-03"), ("INV-2026-0302", "Acme Supplies", 8500, "2026-03-05"),
    ("INV-2026-0303", "BlueSky Logistics", 23400, "2026-03-08"), ("INV-2026-0304", "BlueSky Logistics", 15750, "2026-03-11"),
    ("INV-2026-0305", "Cedar Stationery", 3200, "2026-03-13"), ("INV-2026-0306", "Delta Cloud", 56000, "2026-03-15"),
    ("INV-2026-0307", "Evergreen Facilities", 18900, "2026-03-19"), ("INV-2026-0308", "Evergreen Facilities", 7600, "2026-03-26"),
]


def conn(name: str) -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / f"{name}.db", timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init(name: str) -> None:
    c = conn(name)
    c.executescript(SCHEMAS[name])
    if name == "hr" and not c.execute("SELECT 1 FROM employees").fetchone():
        c.executemany("INSERT INTO employees(emp_code,name,email,department,cost_center,manager,start_date) VALUES (?,?,?,?,?,?,?)", EMPLOYEES)
    if name == "expense" and not c.execute("SELECT 1 FROM ledger").fetchone():
        c.executemany("INSERT INTO ledger(invoice_no,vendor,amount_inr,posted_at) VALUES (?,?,?,?)", LEDGER)
    c.commit()
    c.close()


def init_all() -> None:
    for n in SCHEMAS:
        init(n)


def reset_all() -> None:
    """Fresh company state for eval runs. Generated inputs (receipts, templates, invoices) are kept."""
    for n in SCHEMAS:
        (DATA / f"{n}.db").unlink(missing_ok=True)
    for d in ("uploads", "out"):
        shutil.rmtree(DATA / d, ignore_errors=True)
    init_all()
