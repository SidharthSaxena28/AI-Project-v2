import pytest

from ai_operator import tools
from ai_operator.core.state import RunContext


@pytest.fixture(scope="session", autouse=True)
def _tools_and_data():
    tools.load_all()
    from company_env.data import make_data
    make_data.main()


@pytest.fixture
def ctx(tmp_path):
    return RunContext("t1", root=str(tmp_path))


@pytest.fixture
def clean_env():
    from company_env.common import db, web
    db.reset_all()
    web.reset_fault_state()
    yield
    web.reset_fault_state()
