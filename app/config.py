from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    app_storage_secret: str = Field(min_length=32, alias="APP_STORAGE_SECRET")
    staff_signup_code: str = Field(min_length=12, alias="STAFF_SIGNUP_CODE")
    serpapi_api_key: str = Field(alias="SERPAPI_API_KEY")
    
    ollama_model: str = Field(default="qwen3:8b", alias="OLLAMA_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    code_runner_url: str = Field(default="http://runner:8090", alias="CODE_RUNNER_URL")

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    app_name: str = ("Placement Readiness Portal")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

settings = Settings()