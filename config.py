from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from datetime import datetime


class Settings(BaseSettings):
    # APP SETTINGS
    OPENAI_API_KEY: str = Field(..., description="API key para OpenAI")
    MODEL_URL: str = Field(
        default="wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
        description="URL del modelo de OpenAI"
    )
    PROMPT_FILE: str = Field(default="", description="Ruta al archivo de prompt del sistema")
    LOG_FILE: str = Field(default="logs/log_", description="Prefijo para el archivo de log")
    
    # VOICE SETTINGS
    THRESHOLD: float = Field(default=0.99, description="Umbral de detección de voz (0 a 1)")
    PREFIX_PADDING_MS: int = Field(default=300, description="Grabación de silencio antes de detectar voz")
    SILENCE_DURATION_MS: int = Field(default=3000, description="Duración de silencio para cortar la grabación")
    
    # TRANSCRIPTION SETTINGS
    LANGUAGE: str = Field(default="es", description="Idioma para la transcripción")
    VOICE: str = Field(default="marin", description="Voz para la respuesta de OpenAI")
    MODEL_NAME: str = Field(default="", description="Modelo de transcripción")
    
    # HARDWARE
    MIC_INDEX: Optional[int] = Field(default=None, description="Índice del micrófono")
    SPEAKER_INDEX: Optional[int] = Field(default=None, description="Índice del altavoz")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        
    @property
    def log_file_with_timestamp(self) -> str:
        """Genera el nombre del archivo de log con timestamp actual"""
        return f"{self.LOG_FILE}.{datetime.now().strftime('%Y.%m.%d_%H.%M.%S')}.log"


@lru_cache()
def get_settings() -> Settings:
    """
    Función singleton para obtener la configuración de la aplicación.
    Usa lru_cache para asegurar que la configuración se cargue una sola vez.
    """
    return Settings()