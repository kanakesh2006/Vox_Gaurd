from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SARVAM_API_KEY: str = ""
    AMOUNT_THRESHOLD: int = 10000
    DURESS_THRESHOLD: float = 1.5
    STEPUP_THRESHOLD: float = 1.0
    PORT: int = 8001
    HOST: str = "0.0.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
