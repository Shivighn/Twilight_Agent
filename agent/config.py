import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required env var: {key}")
    return val


class Config:
    # NVIDIA NIM free cloud endpoints, falling back to OpenRouter on error.
    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY", "")
    nvidia_base_url: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    nvidia_vision_model: str = os.getenv("NVIDIA_VISION_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    nvidia_chat_model: str = os.getenv("NVIDIA_CHAT_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    nvidia_timeout: int = int(os.getenv("NVIDIA_TIMEOUT_MS", "90000")) // 1000

    # OpenRouter — fallback when NVIDIA fails (free tier: 20 req/min, 50 req/day shared pool)
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_vision_model: str = os.getenv("OPENROUTER_VISION_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
    openrouter_chat_model: str = os.getenv("OPENROUTER_CHAT_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
    openrouter_timeout: int = int(os.getenv("OPENROUTER_TIMEOUT_MS", "90000")) // 1000

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_chat_model: str = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-20b")
    groq_timeout: int = int(os.getenv("GROQ_TIMEOUT_MS", "30000")) // 1000

    storage_dir: str = os.getenv("STORAGE_DIR", "./storage")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    supabase_url: str = _require("SUPABASE_URL")
    supabase_service_role_key: str = _require("SUPABASE_SERVICE_ROLE_KEY")

    # Petpooja Captain Order Automation — see
    # docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md. Off by default: a bad/
    # incomplete config here must never start intercepting messages until
    # someone deliberately turns it on, same reasoning as every Node-side
    # feature flag in src/config/index.js.
    petpooja_orders_enabled: bool = os.getenv("PETPOOJA_ORDERS_ENABLED", "false").lower() == "true"
    petpooja_orders_whatsapp_group_name: str = os.getenv("PETPOOJA_ORDERS_WHATSAPP_GROUP_NAME", "")
    # 'dummy_api' (default): real HTTP round trip against our own local
    # simulation of Petpooja's actual API shape — see dummy_petpooja_api.py.
    # 'mock': pure in-process, no network, for unit tests. 'real': pending
    # verified staging credentials (requirement 8).
    petpooja_order_provider: str = os.getenv("PETPOOJA_ORDER_PROVIDER", "dummy_api")
    petpooja_dummy_api_base_url: str = os.getenv("PETPOOJA_DUMMY_API_BASE_URL", "http://127.0.0.1:8000/dummy-petpooja")
    petpooja_rest_id: str = os.getenv("PETPOOJA_REST_ID", "DUMMY-REST-ID")

    # 'real' provider (staging today, production later — see
    # petpooja_order_provider.py's RealPetpoojaOrderProvider). Staging vs.
    # production is meant to be exactly this: swap these four values in
    # .env, nothing else — same save_order URL pattern, different
    # credentials (Petpooja will confirm if production's URL differs).
    petpooja_app_key: str = os.getenv("PETPOOJA_APP_KEY", "")
    petpooja_app_secret: str = os.getenv("PETPOOJA_APP_SECRET", "")
    petpooja_access_token: str = os.getenv("PETPOOJA_ACCESS_TOKEN", "")
    petpooja_save_order_url: str = os.getenv(
        "PETPOOJA_SAVE_ORDER_URL",
        "https://qle1yy2ydc.execute-api.ap-southeast-1.amazonaws.com/V1/save_order",
    )
    # Where Petpooja calls US back with order status updates. No public
    # endpoint exists yet (this agent isn't deployed anywhere reachable
    # from the internet) — a placeholder is fine for now, it just means
    # status callbacks won't arrive until this is deployed with a real
    # domain. See docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md's Phase 1
    # limitation note.
    petpooja_callback_url: str = os.getenv("PETPOOJA_CALLBACK_URL", "")

    # petpooja_captain_orders lives in its OWN Supabase project — separate
    # from SUPABASE_URL above (which every other feature shares) — falls
    # back to the same project only if no dedicated one is configured.
    petpooja_supabase_url: str = os.getenv("PETPOOJA_SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")
    petpooja_supabase_service_role_key: str = os.getenv("PETPOOJA_SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


config = Config()
