import logging
import asyncio
from typing import Dict, Any, Optional
from .abstract_tts_client import AbstractTTSClient
from .voicevox_client import VoicevoxClient
from .dummy_tts_client import DummyTTSClient

logger = logging.getLogger("src.discord_bot")

class TTSClientFactory:
    """
    設定に基づいて適切なTTSクライアントを作成するファクトリークラス。
    """

    @staticmethod
    async def create_tts_client(engine_name: str, config: Dict[str, Any], enable_fallback: bool = True) -> AbstractTTSClient:
        """
        指定されたエンジン名と設定に基づいてTTSクライアントを作成します。

        Args:
            engine_name (str): TTSエンジンの名前（例: "voicevox", "dummy"）
            config (Dict[str, Any]): TTSエンジンの設定
            enable_fallback (bool): エンジンが利用できない場合にDummyTTSClientにフォールバックするかどうか

        Returns:
            AbstractTTSClient: 作成されたTTSクライアント

        Raises:
            ValueError: サポートされていないエンジン名が指定された場合
        """
        logger.info(f"Creating TTS client for engine: {engine_name}")

        if engine_name.lower() == "voicevox":
            return await TTSClientFactory._create_voicevox_client(config, enable_fallback)
        elif engine_name.lower() == "dummy":
            return DummyTTSClient()
        else:
            available_engines = ["voicevox", "dummy"]
            error_msg = f"Unsupported TTS engine: {engine_name}. Available engines: {available_engines}"
            logger.error(error_msg)
            
            if enable_fallback:
                logger.warning("Falling back to dummy TTS client")
                return DummyTTSClient()
            else:
                raise ValueError(error_msg)    @staticmethod
    async def _create_voicevox_client(config: Dict[str, Any], enable_fallback: bool) -> AbstractTTSClient:
        """
        VoiceVoxクライアントを作成し、利用可能性をチェックします。

        Args:
            config (Dict[str, Any]): VoiceVox設定
            enable_fallback (bool): 利用不可の場合にダミーにフォールバックするかどうか

        Returns:
            AbstractTTSClient: VoiceVoxクライアントまたはダミークライアント
        """
        try:
            base_url = config.get("base_url", "http://127.0.0.1:50021")
            timeout = config.get("timeout", 10)
            
            logger.info(f"Creating VoiceVox client with base_url: {base_url}, timeout: {timeout}")
            voicevox_client = VoicevoxClient(base_url=base_url, timeout=timeout)
            
            # 利用可能性をチェック（短時間でタイムアウト）
            try:
                is_available = await asyncio.wait_for(voicevox_client.check_availability(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("VoiceVox availability check timed out")
                is_available = False
            
            if is_available:
                logger.info("VoiceVox engine is available and ready")
                return voicevox_client
            else:
                logger.warning("VoiceVox engine is not available")
                try:
                    await voicevox_client.close()  # クリーンアップ
                except Exception as cleanup_error:
                    logger.warning(f"Error during VoiceVox client cleanup: {cleanup_error}")
                
                if enable_fallback:
                    logger.warning("Falling back to dummy TTS client")
                    return DummyTTSClient()
                else:
                    raise RuntimeError("VoiceVox engine is not available and fallback is disabled")
                    
        except Exception as e:
            logger.error(f"Failed to create VoiceVox client: {e}", exc_info=True)
            
            if enable_fallback:
                logger.warning("Falling back to dummy TTS client due to VoiceVox initialization error")
                return DummyTTSClient()
            else:
                raise
