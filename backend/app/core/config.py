from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Postgres
    postgres_user: str = Field(..., env="POSTGRES_USER")
    postgres_password: str = Field(..., env="POSTGRES_PASSWORD")
    postgres_db: str = Field(..., env="POSTGRES_DB")
    postgres_host: str = Field(..., env="POSTGRES_HOST")
    postgres_port: int = Field(..., env="POSTGRES_PORT")

    # Redis
    redis_host: str = Field(..., env="REDIS_HOST")
    redis_port: int = Field(..., env="REDIS_PORT")
    redis_db: int = Field(..., env="REDIS_DB")

    # Auth / Security
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = Field(..., env="ALGORITHM")
    access_token_expire_minutes: int = Field(..., env="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Optional general settings
    debug: bool = Field(False, env="DEBUG")
    project_name: str = Field("My Project", env="PROJECT_NAME")
    api_v1_str: str = Field("/api/v1", env="API_V1_STR")

    # Derived property
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {
        "env_file": ".env",
        "extra": "ignore", 
    }

settings = Settings()
