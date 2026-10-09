from ai_operator.core.models import Postcondition, Step
from ai_operator.core.planner import validate_steps

TOOLS = {"files.read_pdf", "browser.click", "sql.query"}


def test_state_changing_step_needs_postcondition():
    assert validate_steps([Step(id="s1", goal="g", tool_hint="browser.click", state_changing=True)], TOOLS)
    ok = Step(id="s1", goal="g", tool_hint="browser.click", state_changing=True, postconditions=[Postcondition(kind="sql")])
    assert not validate_steps([ok], TOOLS)


def test_unknown_tool_rejected_and_human_steps_exempt():
    assert validate_steps([Step(id="s1", goal="g", tool_hint="shell.exec")], TOOLS)
    assert not validate_steps([Step(id="s1", goal="ok?", kind="human", state_changing=True)], TOOLS)


def test_step_limit_and_duplicate_ids():
    many = [Step(id=f"s{i}", goal="g") for i in range(13)]
    assert any("maximum" in p for p in validate_steps(many, TOOLS))
    assert any("duplicate" in p for p in validate_steps([Step(id="a", goal="g"), Step(id="a", goal="g")], TOOLS))
