from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""

    # Groq (free alternative)
    groq_api_key: str = ""

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "kaigo-services"
    pinecone_environment: str = "us-east-1"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # LINE
    line_channel_access_token: str = ""
    line_channel_secret: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    embedding_model: str = "intfloat/multilingual-e5-large"
    orchestrator_model: str = "llama-3.3-70b-versatile"
    critic_model: str = "llama-3.1-8b-instant"

    # MHLW scraper
    mhlw_base_url: str = "https://www.kaigokensaku.mhlw.go.jp"
    tokyo_pref_code: str = "13"

    # Tokyo wards (区) — 23 special wards
    tokyo_wards: list[str] = [
        "千代田区", "中央区", "港区", "新宿区", "文京区",
        "台東区", "墨田区", "江東区", "品川区", "目黒区",
        "大田区", "世田谷区", "渋谷区", "中野区", "杉並区",
        "豊島区", "北区", "荒川区", "板橋区", "練馬区",
        "足立区", "葛飾区", "江戸川区",
    ]

    # Care service type codes (介護保険サービス種別)
    service_type_codes: dict[str, str] = {
        "11": "訪問介護 (Home Visit Care)",
        "12": "訪問入浴介護 (Home Visit Bathing)",
        "13": "訪問看護 (Home Visit Nursing)",
        "14": "訪問リハビリ (Home Visit Rehabilitation)",
        "21": "通所介護 (Day Service)",
        "22": "通所リハビリ (Day Rehabilitation)",
        "31": "短期入所生活介護 (Short-Stay Care)",
        "41": "特別養護老人ホーム (Special Nursing Home)",
        "42": "介護老人保健施設 (Care Health Facility)",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
