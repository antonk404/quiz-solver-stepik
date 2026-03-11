from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    gemini_api_key: str = Field(validation_alias="GEMINI_API_KEY")
    headless: bool = Field(validation_alias="HEADLESS")
    retry_attempts: int = Field(validation_alias="RETRY_ATTEMPTS")
    timeout: int = Field(validation_alias="TIMEOUT") # мс для playwright

    log_level: str = Field(validation_alias="LOG_LEVEL")

    STEPIK_USER_DATA_DIR: str

    @property
    def stepik_user_data_dir(self) -> Path:
        return Path(self.STEPIK_USER_DATA_DIR)

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
