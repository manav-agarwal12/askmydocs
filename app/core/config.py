from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All environment values live here, loaded once from .env."""

    DATABASE_URL: str
    REDIS_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    GEMINI_API_KEY: str = ""
    UPLOAD_DIR: str = "./uploads"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()