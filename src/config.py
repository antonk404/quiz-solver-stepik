from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator


class Settings(BaseSettings):
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    headless: bool = Field(default=False, validation_alias="HEADLESS")
    retry_attempts: int = Field(default=3, validation_alias="RETRY_ATTEMPTS")
    timeout: int = Field(default=15000, validation_alias="TIMEOUT")  # мс для playwright

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    STEPIK_USER_DATA_DIR: str = "../browser_session"

    stepik_web: str = Field(default="https://stepik.org/catalog", validation_alias="STEPIK_WEB")

    # Быстрый профиль по умолчанию: минимизируем ретраи и ожидания.
    fast_mode: bool = Field(default=True, validation_alias="FAST_MODE")
    ai_max_reasks: int = Field(default=0, validation_alias="AI_MAX_REASKS")
    step_solve_attempts: int = Field(default=2, validation_alias="STEP_SOLVE_ATTEMPTS")
    api_retry_attempts: int = Field(default=2, validation_alias="API_RETRY_ATTEMPTS")
    main_loop_delay_sec: float = Field(default=0.1, validation_alias="MAIN_LOOP_DELAY_SEC")
    submit_wait_timeout_ms: int = Field(default=2000, validation_alias="SUBMIT_WAIT_TIMEOUT_MS")
    feedback_wait_timeout_ms: int = Field(default=2000, validation_alias="FEEDBACK_WAIT_TIMEOUT_MS")

    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")
    ai_provider: str = Field(default="gemini", validation_alias="AI_PROVIDER")  # "gemini", "groq", "auto"

    @property
    def stepik_user_data_dir(self) -> Path:
        return Path(self.STEPIK_USER_DATA_DIR)

    @model_validator(mode="after")
    def validate_ai_provider_settings(self) -> "Settings":
        provider = self.ai_provider.strip().lower()
        self.ai_provider = provider

        if provider not in {"gemini", "groq", "auto"}:
            raise ValueError("AI_PROVIDER должен быть одним из: gemini, groq, auto.")

        if provider == "gemini" and not self.gemini_api_key.strip():
            raise ValueError("Для AI_PROVIDER=gemini требуется GEMINI_API_KEY.")

        if provider == "groq" and not self.groq_api_key.strip():
            raise ValueError("Для AI_PROVIDER=groq требуется GROQ_API_KEY.")

        if provider == "auto" and not (
            self.gemini_api_key.strip() or self.groq_api_key.strip()
        ):
            raise ValueError(
                "Для AI_PROVIDER=auto требуется хотя бы один ключ: GEMINI_API_KEY или GROQ_API_KEY."
            )

        return self

    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8")


settings = Settings()
