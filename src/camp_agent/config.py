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
