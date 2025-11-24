from typing import List

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PINECONE_API_KEY: str
    PINECONE_ENVIRONMENT: str
    PINECONE_INDEX: str
    PINECONE_DIM: int

    # S3_ENDPOINT: str
    # S3_ACCESS_KEY: str
    # S3_SECRET_KEY: str
    # S3_BUCKET: str

    MONGO_URI: str
    MONGO_DB: str

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"

    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 200

    OPENAI_API_KEY: str
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]


    class Config:
        env_file = ".env"

settings = Settings()
