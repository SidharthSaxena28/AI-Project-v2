"""Mock expense portal. Run: uvicorn company_env.expense_portal.app:app --port 8001"""
import hashlib
import re

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from company_env.common import db
from company_env.common.web import STATE, faults, make_app, page

BRAND = "Expense Portal"
NAV = [("/", "Claims"), ("/claims/new", "New claim"), ("/ledger", "AP ledger")]
app = make_app(BRAND, lambda: db.init("expense"))

FORM = """<h2>New expense claim</h2>
{% for e in errors %}<div class=err>{{ e }}</div>{% endfor %}
<form method=post action="/claims" enctype="multipart/form-data">
<label for=employee>Employee (full name)</label><input id=employee name=employee value="{{ v.employee }}">
<label for=trip>Trip / description</label><input id=trip name=trip value="{{ v.trip }}">
<label for=category>Category</label><select id=category name=category>
{% for c in ['Travel','Meals','Lodging','Other'] %}<option value="{{ c }}" {{ 'selected' if v.category==c }}>{{ c }}</option>{% endfor %}</select>
<label for=amount_inr>Total amount (INR)</label><input id=amount_inr name=amount_inr value="{{ v.amount_inr }}">
<label for=cost_center>Cost center</label><input id=cost_center name=cost_center value="{{ v.cost_center }}" placeholder="CC-0000">
{% if show_project %}<label for=project_code>Project code</label><input id=project_code name=project_code value="{{ v.project_code }}" placeholder="PRJ-...">{% endif %}
<label for=receipts>Receipts (attach all)</label><input id=receipts name=receipts type=file multiple>
<button type=submit>Submit claim</button></form>"""

LIST = """<h2>Claims</h2><table><tr><th>ID<th>Employee<th>Trip<th>Amount (INR)<th>Cost center<th>Status</tr>
{% for c in claims %}<tr><td><a href="/claims/{{ c.id }}">#{{ c.id }}</a><td>{{ c.employee }}<td>{{ c.trip }}<td>{{ c.amount_inr }}<td>{{ c.cost_center }}<td>{{ c.status }}</tr>
{% else %}<tr><td colspan=6>No claims yet.</tr>{% endfor %}</table>"""

DETAIL = """<h2>Claim #{{ c.id }} - {{ c.status }}</h2><p><b>{{ c.employee }}</b> · {{ c.trip }} · {{ c.category }}</p>
<p>Amount: INR {{ c.amount_inr }} · Cost center {{ c.cost_center }}{% if c.project_code %} · Project {{ c.project_code }}{% endif %}</p>
<h3>Receipts ({{ receipts|length }})</h3><ul>{% for r in receipts %}<li>{{ r.filename }} <code>{{ r.sha256[:10] }}</code></li>{% endfor %}</ul>"""

LEDGER = """<h2>AP ledger</h2><table><tr><th>Invoice<th>Vendor<th>Amount (INR)<th>Posted</tr>
{% for r in rows %}<tr><td>{{ r.invoice_no }}<td>{{ r.vendor }}<td>{{ r.amount_inr }}<td>{{ r.posted_at }}</tr>{% endfor %}</table>"""

FIELDS = ("employee", "trip", "category", "amount_inr", "cost_center", "project_code")


def _form(request, values=None, errors=(), status=200):
    v = {k: "" for k in FIELDS} | (values or {})
    show = "validation" in faults() and STATE["validation_shown"]
    return page(request, BRAND, NAV, FORM, status=status, v=v, errors=list(errors), show_project=show)


def _rows(sql, args=()):
    c = db.conn("expense")
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@app.get("/")
def index(request: Request):
    return page(request, BRAND, NAV, LIST, claims=_rows("SELECT * FROM claims ORDER BY id DESC"))


@app.get("/claims/new")
def new_form(request: Request):
    return _form(request)


@app.post("/claims")
async def create(request: Request, employee: str = Form(""), trip: str = Form(""), category: str = Form(""),
                 amount_inr: str = Form(""), cost_center: str = Form(""), project_code: str = Form(""),
                 receipts: list[UploadFile] = File(default=[])):
    values = dict(employee=employee, trip=trip, category=category, amount_inr=amount_inr, cost_center=cost_center, project_code=project_code)
    files = [f for f in receipts if f.filename]
    errors = []
    if not employee.strip():
        errors.append("Employee is required.")
    if not trip.strip():
        errors.append("Trip / description is required.")
    try:
        if float(amount_inr.replace(",", "")) <= 0:
            raise ValueError
    except ValueError:
        errors.append("Amount must be a positive number.")
    if not re.fullmatch(r"CC-\d{4}", cost_center.strip()):
        errors.append("Cost center must look like CC-1234.")
    if not files:
        errors.append("At least one receipt is required.")
    if "validation" in faults() and not project_code.strip().startswith("PRJ-"):
        STATE["validation_shown"] = True
        errors.append("Project code is required for this claim (format PRJ-XXX-NN).")
    if errors:
        return _form(request, values, errors, status=422)
    c = db.conn("expense")
    cur = c.execute("INSERT INTO claims(employee,trip,category,amount_inr,cost_center,project_code,status) VALUES (?,?,?,?,?,?, 'pending_approval')",
                    (employee.strip(), trip.strip(), category, float(amount_inr.replace(",", "")), cost_center.strip(), project_code.strip()))
    cid = cur.lastrowid
    up = db.DATA / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    for f in files:
        data = await f.read()
        (up / f"{cid}_{f.filename}").write_bytes(data)
        c.execute("INSERT INTO receipts(claim_id,filename,sha256) VALUES (?,?,?)", (cid, f.filename, hashlib.sha256(data).hexdigest()))
    c.commit()
    c.close()
    return RedirectResponse(f"/claims/{cid}", status_code=303)


@app.get("/claims/{cid}")
def detail(request: Request, cid: int):
    rows = _rows("SELECT * FROM claims WHERE id=?", (cid,))
    if not rows:
        return page(request, BRAND, NAV, "<h2>Not found</h2>", status=404)
    return page(request, BRAND, NAV, DETAIL, c=rows[0], receipts=_rows("SELECT * FROM receipts WHERE claim_id=?", (cid,)))


@app.get("/ledger")
def ledger(request: Request):
    return page(request, BRAND, NAV, LEDGER, rows=_rows("SELECT * FROM ledger ORDER BY invoice_no"))


@app.get("/api/claims")
def api_claims():
    return _rows("SELECT * FROM claims ORDER BY id")


@app.get("/api/ledger")
def api_ledger():
    return _rows("SELECT * FROM ledger ORDER BY invoice_no")
