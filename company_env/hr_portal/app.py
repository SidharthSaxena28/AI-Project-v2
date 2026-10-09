"""Mock HR portal. Run: uvicorn company_env.hr_portal.app:app --port 8002"""
from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from company_env.common import db
from company_env.common.web import make_app, page

BRAND = "HR Portal"
NAV = [("/", "Employees"), ("/employees/new", "New employee")]
app = make_app(BRAND, lambda: db.init("hr"))
SYSTEMS = ["email", "vpn", "github", "slack"]

LIST = """<h2>Employees</h2><table><tr><th>Code<th>Name<th>Email<th>Dept<th>Cost center<th>Manager<th>Start<th>Status</tr>
{% for e in emps %}<tr><td><a href="/employees/{{ e.emp_code }}">{{ e.emp_code }}</a><td>{{ e.name }}<td>{{ e.email }}<td>{{ e.department }}<td>{{ e.cost_center }}<td>{{ e.manager }}<td>{{ e.start_date }}<td>{{ e.status }}</tr>{% endfor %}</table>"""

FORM = """<h2>New employee record</h2>{% for e in errors %}<div class=err>{{ e }}</div>{% endfor %}
<form method=post action="/employees">
<label for=name>Full name</label><input id=name name=name value="{{ v.name }}">
<label for=email>Personal / work email</label><input id=email name=email value="{{ v.email }}">
<label for=department>Department</label><input id=department name=department value="{{ v.department }}">
<label for=cost_center>Cost center</label><input id=cost_center name=cost_center value="{{ v.cost_center }}" placeholder="CC-0000">
<label for=manager>Manager (full name)</label><input id=manager name=manager value="{{ v.manager }}">
<label for=start_date>Start date (YYYY-MM-DD)</label><input id=start_date name=start_date value="{{ v.start_date }}">
<button type=submit>Create employee</button></form>"""

DETAIL = """<h2>{{ e.name }} <small>({{ e.emp_code }})</small></h2><p>{{ e.department }} · {{ e.cost_center }} · manager {{ e.manager }} · starts {{ e.start_date }}</p>
<h3>Accounts ({{ accounts|length }})</h3><ul>{% for a in accounts %}<li>{{ a.system }}: {{ a.username }}</li>{% endfor %}</ul>
<a href="/employees/{{ e.emp_code }}/accounts/new">Add account</a>"""

ACCT = """<h2>Create system account for {{ e.name }}</h2>{% for er in errors %}<div class=err>{{ er }}</div>{% endfor %}
<form method=post action="/employees/{{ e.emp_code }}/accounts"><label for=system>System</label><select id=system name=system>
{% for s in systems %}<option value="{{ s }}">{{ s }}</option>{% endfor %}</select>
<button type=submit>Create account</button></form>"""

FIELDS = ("name", "email", "department", "cost_center", "manager", "start_date")


def _q(sql, args=()):
    c = db.conn("hr")
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@app.get("/")
def index(request: Request):
    return page(request, BRAND, NAV, LIST, emps=_q("SELECT * FROM employees ORDER BY id"))


@app.get("/employees/new")
def new(request: Request):
    return page(request, BRAND, NAV, FORM, v={k: "" for k in FIELDS}, errors=[])


@app.post("/employees")
def create(request: Request, name: str = Form(""), email: str = Form(""), department: str = Form(""), cost_center: str = Form(""),
           manager: str = Form(""), start_date: str = Form("")):
    v = dict(name=name, email=email, department=department, cost_center=cost_center, manager=manager, start_date=start_date)
    errors = [f"{k.replace('_', ' ').title()} is required." for k, val in v.items() if not val.strip()]
    if _q("SELECT 1 FROM employees WHERE email=?", (email.strip(),)):
        errors.append("An employee with this email already exists.")
    if errors:
        return page(request, BRAND, NAV, FORM, status=422, v=v, errors=errors)
    c = db.conn("hr")
    n = c.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    code = f"EMP-{1100 + n}"
    c.execute("INSERT INTO employees(emp_code,name,email,department,cost_center,manager,start_date) VALUES (?,?,?,?,?,?,?)",
              (code, name.strip(), email.strip(), department.strip(), cost_center.strip(), manager.strip(), start_date.strip()))
    c.commit()
    c.close()
    return RedirectResponse(f"/employees/{code}", status_code=303)


@app.get("/employees/{code}")
def detail(request: Request, code: str):
    e = _q("SELECT * FROM employees WHERE emp_code=?", (code,))
    if not e:
        return page(request, BRAND, NAV, "<h2>Not found</h2>", status=404)
    return page(request, BRAND, NAV, DETAIL, e=e[0], accounts=_q("SELECT * FROM accounts WHERE emp_code=?", (code,)))


@app.get("/employees/{code}/accounts/new")
def acct_form(request: Request, code: str):
    e = _q("SELECT * FROM employees WHERE emp_code=?", (code,))
    return page(request, BRAND, NAV, ACCT, e=e[0], systems=SYSTEMS, errors=[])


@app.post("/employees/{code}/accounts")
def acct_create(request: Request, code: str, system: str = Form("")):
    e = _q("SELECT * FROM employees WHERE emp_code=?", (code,))
    if not e or system not in SYSTEMS:
        return page(request, BRAND, NAV, "<h2>Invalid request</h2>", status=422)
    username = e[0]["name"].lower().replace(" ", ".")
    c = db.conn("hr")
    try:
        c.execute("INSERT INTO accounts(emp_code,system,username) VALUES (?,?,?)", (code, system, username))
        c.commit()
    except Exception:
        c.close()
        return page(request, BRAND, NAV, ACCT, status=422, e=e[0], systems=SYSTEMS, errors=[f"{system} account already exists."])
    c.close()
    return RedirectResponse(f"/employees/{code}", status_code=303)


@app.get("/api/employees")
def api_employees():
    return _q("SELECT * FROM employees ORDER BY id")
