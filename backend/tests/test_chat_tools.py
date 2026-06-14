from app.chat.tools import TOOLS, TOOL_BY_NAME, ChatContext, ChatTool
from app.config.cache import Cache
from app.models.schemas import Settings
from tests.test_analyzer import FakeProvider


def _ctx():
    return ChatContext(settings=Settings(), cache=Cache(":memory:"),
                       provider=FakeProvider([]), prediction_store=None)


def test_chat_context_holds_dependencies():
    ctx = _ctx()
    assert ctx.settings.active_provider == "anthropic"
    assert ctx.prediction_store is None


def test_chat_tool_dataclass_fields():
    t = ChatTool("echo", "echoes", '{"q": str}', lambda args, ctx: "ok")
    assert t.name == "echo"
    assert t.run({}, None) == "ok"
