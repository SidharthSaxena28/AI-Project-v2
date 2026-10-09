"""Mock portals + fault injection via FastAPI's TestClient (no browser, no LLM)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from company_env.common import db
from company_env.expense_portal.app import app

FORM = dict(employee="Priya Sharma", trip="Mumbai", category="Travel", amount_inr="8420", cost_center="CC-4410")
RECEIPT = ("r.pdf", b"%PDF-1.4 fake", "application/pdf")


@pytest.fixture
def client(clean_env, monkeypatch):
    monkeypatch.delenv("FAULTS", raising=False)
    c = TestClient(app, follow_redirects=False)
    assert c.post("/login", data={"username": "operator", "password": "operator123"}).status_code == 303
    return c


def claims():
    return sqlite3.connect(db.DATA / "expense.db").execute("SELECT employee, amount_inr, status FROM claims").fetchall()


def post(c, **over):
    return c.post("/claims", data={**FORM, **over}, files=[("receipts", RECEIPT)])


def test_login_required():
    c = TestClient(app, follow_redirects=False)
    assert c.get("/").status_code == 303 and "/login" in c.get("/").headers["location"]
    assert c.get("/api/claims").status_code == 200            # verifier API stays open


def test_create_claim_lands_in_sqlite(client):
    r = post(client)
    assert r.status_code == 303 and claims() == [("Priya Sharma", 8420.0, "pending_approval")]


def test_form_validation(client):
    assert post(client, cost_center="bad").status_code == 422 and claims() == []


def test_flaky_500_first_post_only(client, monkeypatch):
    monkeypatch.setenv("FAULTS", "flaky_500")
    assert post(client).status_code == 500 and claims() == []
    assert post(client).status_code == 303 and len(claims()) == 1


def test_validation_fault_reveals_project_code(client, monkeypatch):
    monkeypatch.setenv("FAULTS", "validation")
    assert "project_code" not in client.get("/claims/new").text
    r = post(client)
    assert r.status_code == 422 and "Project code is required" in r.text and 'name="project_code"' in r.text.replace("name=project_code", 'name="project_code"')
    assert post(client, project_code="PRJ-SAL-22").status_code == 303


def test_rename_button_and_modal(client, monkeypatch):
    monkeypatch.setenv("FAULTS", "rename_button,modal")
    t = client.get("/claims/new").text
    assert "File reimbursement" in t and "Submit claim" not in t and "op-modal" in t


def test_session_expiry(client, monkeypatch):
    monkeypatch.setenv("FAULTS", "session_expiry")
    monkeypatch.setenv("FAULT_SESSION_REQS", "3")
    statuses = [client.get("/").status_code for _ in range(4)]
    assert statuses[-1] == 303 and statuses[0] == 200
