from datetime import time
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://camp:camp@localhost:5432/camp"
    db_connect_timeout_s: int = 2
    secret_key: str = "demo-only-set-SECRET_KEY-in-production"
    camp_timezone: str = "Europe/London"
    cookie_secure: bool = False
    case_cookie_max_age_s: int = 14 * 24 * 3600
    run_lease_s: int = 120
    rate_limit_messages: int = 20
    rate_limit_window_s: int = 600

    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-4.1-mini"
    llm_timeout_s: float = 20.0
    llm_attempts: int = 3
    llm_retry_delay_s: float = 1.0
    ticket_attempts: int = 3
    ticket_retry_delay_s: float = 1.0

    safety_terms: list[str] = ["fire", "gas", "smoke", "flood", "medical", "injury"]
    held_categories: list[str] = ["refund", "compensation", "cabin_move", "safety_close_out"]
    clarify_max_rounds: int = 2
    step_up_case_failures: int = 3
    step_up_ip_failures: int = 3
    step_up_ip_window_s: int = 3600
    guide_path: Path = Path("data/camp-guide.md")
    stays_path: Path = Path("data/stays.json")

    staff_user: str = "staff"
    staff_password: SecretStr = SecretStr("demo-only-set-STAFF_PASSWORD")
    desk_opens: time = time(8)
    desk_closes: time = time(22)
    gate_timeout_s: int = 900
    reopen_window_s: int = 24 * 3600
    outbox_poll_s: float = 2.0
