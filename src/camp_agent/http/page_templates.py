from pathlib import Path

from fastapi.templating import Jinja2Templates

from camp_agent.domain.quick_pick import QuickPick

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["picks"] = list(QuickPick)
