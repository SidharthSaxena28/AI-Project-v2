"""Mock IT ticketing. Run: uvicorn company_env.ticketing.app:app --port 8003"""
from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from company_env.common import db
from company_env.common.web import make_app, page

BRAND = "IT Ticketing"
NAV = [("/", "Tickets"), ("/tickets/new", "New ticket")]
app = make_app(BRAND, lambda: db.init("ticketing"))
CATS = ["Hardware", "Access", "Finance follow-up", "Other"]

LIST = """<h2>Tickets</h2><table><tr><th>ID<th>Title<th>Category<th>Requester<th>Status</tr>
{% for t in tickets %}<tr><td><a href="/tickets/{{ t.id }}">#{{ t.id }}</a><td>{{ t.title }}<td>{{ t.category }}<td>{{ t.requester }}<td>{{ t.status }}</tr>
{% else %}<tr><td colspan=5>No tickets.</tr>{% endfor %}</table>"""

FORM = """<h2>New ticket</h2>{% for e in errors %}<div class=err>{{ e }}</div>{% endfor %}
<form method=post action="/tickets"><label for=title>Title</label><input id=title name=title value="{{ v.title }}">
<label for=category>Category</label><select id=category name=category>{% for c in cats %}<option value="{{ c }}">{{ c }}</option>{% endfor %}</select>
<label for=requester>Requester</label><input id=requester name=requester value="{{ v.requester }}">
<label for=body>Details</label><textarea id=body name=body rows=5>{{ v.body }}</textarea>
<button type=submit>Open ticket</button></form>"""

DETAIL = """<h2>Ticket #{{ t.id }} - {{ t.status }}</h2><p><b>{{ t.title }}</b> ({{ t.category }}) · requester {{ t.requester }}</p><pre>{{ t.body }}</pre>"""


def _q(sql, args=()):
    c = db.conn("ticketing")
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@app.get("/")
def index(request: Request):
    return page(request, BRAND, NAV, LIST, tickets=_q("SELECT * FROM tickets ORDER BY id DESC"))


@app.get("/tickets/new")
def new(request: Request):
    return page(request, BRAND, NAV, FORM, v=dict(title="", requester="", body=""), cats=CATS, errors=[])


@app.post("/tickets")
def create(request: Request, title: str = Form(""), category: str = Form("Other"), requester: str = Form(""), body: str = Form("")):
    v = dict(title=title, requester=requester, body=body)
    errors = [f"{k.title()} is required." for k, val in v.items() if not val.strip()]
    if errors:
        return page(request, BRAND, NAV, FORM, status=422, v=v, cats=CATS, errors=errors)
    c = db.conn("ticketing")
    cur = c.execute("INSERT INTO tickets(title,category,requester,assignee,body) VALUES (?,?,?,?,?)",
                    (title.strip(), category, requester.strip(), "it-helpdesk", body.strip()))
    c.commit()
    tid = cur.lastrowid
    c.close()
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@app.get("/tickets/{tid}")
def detail(request: Request, tid: int):
    t = _q("SELECT * FROM tickets WHERE id=?", (tid,))
    if not t:
        return page(request, BRAND, NAV, "<h2>Not found</h2>", status=404)
    return page(request, BRAND, NAV, DETAIL, t=t[0])


@app.get("/api/tickets")
def api_tickets():
    return _q("SELECT * FROM tickets ORDER BY id")
