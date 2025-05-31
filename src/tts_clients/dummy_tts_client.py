import logging
from typing import Optional, Any
from .abstract_tts_client import AbstractTTSClient

logger = logging.getLogger("src.discord_bot")

class DummyTTSClient(AbstractTTSClient):
    """
    TTSエンジンが利用できない場合のダミークライアント。
    実際の音声合成は行わず、常にNoneを返します。
    """

    def __init__(self, **kwargs):
        """
        DummyTTSClientを初期化します。
        """
        logger.info("DummyTTSClient initialized (TTS will be disabled)", extra={"bot_name": "System"})

    async def synthesize_speech(self, text: str, speaker_id: Optional[Any] = None, **kwargs: Any) -> Optional[bytes]:
        """
        音声合成をシミュレートしますが、実際には何も生成しません。

        Args:
            text (str): 音声に変換するテキスト
            speaker_id (Optional[Any]): 話者ID（無視されます）
            **kwargs (Any): 追加パラメータ（無視されます）

        Returns:
            Optional[bytes]: 常にNone（音声データなし）
        """
        logger.warning(f"TTS disabled: Cannot synthesize speech for text: \"{text[:50]}...\"", extra={"bot_name": "System"})
        return None

    async def check_availability(self) -> bool:
        """
        ダミークライアントは常に利用不可として報告します。

        Returns:
            bool: 常にFalse
        """
        return False

    async def close(self):
        """
        ダミークライアントのクローズ処理（何もしません）。
        """
        logger.info("DummyTTSClient closed.", extra={"bot_name": "System"})
