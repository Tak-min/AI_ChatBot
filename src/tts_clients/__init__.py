from typing import Any, Dict, Optional, Type
import logging

from .abstract_tts_client import AbstractTTSClient
from .voicevox_client import VoicevoxClient
from .dummy_tts_client import DummyTTSClient
from .tts_factory import TTSClientFactory

logger = logging.getLogger(__name__)

# 旧来のTTSClientFactory（後方互換のため保持）
class LegacyTTSClientFactory:
    """
    TTSクライアントのインスタンスを生成するファクトリクラス。
    """

    _clients: Dict[str, Type[AbstractTTSClient]] = {
        "voicevox": VoicevoxClient,
        # "generic": GenericTTSClient, # 将来的に追加する場合
    }

    @staticmethod
    def create_client(engine_name: str, config: Dict[str, Any], character_tts_config: Optional[Dict[str, Any]] = None) -> Optional[AbstractTTSClient]:
        """
        指定されたエンジン名のTTSクライアントを生成します。

        Args:
            engine_name (str): TTSエンジンの名前 (例: "voicevox")。
            config (Dict[str, Any]): TTSエンジン全体の設定。
            character_tts_config (Optional[Dict[str, Any]]): キャラクター固有のTTS設定。

        Returns:
            Optional[AbstractTTSClient]: 生成されたTTSクライアントのインスタンス。対応するエンジンがない場合はNone。
        """
        client_class = TTSClientFactory._clients.get(engine_name.lower())
        if client_class:
            try:
                # エンジン全体の設定とキャラクター固有の設定をマージ
                # キャラクター固有の設定が優先される
                final_config = config.get(engine_name.lower(), {}).copy() # エンジン共通設定を取得
                if character_tts_config:
                    final_config.update(character_tts_config) # キャラクター固有設定で上書き
                
                logger.info(f"Creating TTS client for engine: {engine_name} with config: {final_config}")
                return client_class(**final_config) # 設定を展開して渡す
            except Exception as e:
                logger.error(f"Error creating TTS client for {engine_name}: {e}", exc_info=True)
                return None
        else:
            logger.warning(f"No TTS client found for engine: {engine_name}")
            return None

    @staticmethod
    def get_available_engines() -> list[str]:
        """
        利用可能なTTSエンジン名のリストを返します。
        """
        return list(TTSClientFactory._clients.keys())

__all__ = ["AbstractTTSClient", "VoicevoxClient", "DummyTTSClient", "TTSClientFactory", "LegacyTTSClientFactory"]
