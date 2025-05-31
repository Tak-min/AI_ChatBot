from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class AbstractTTSClient(ABC):
    """
    TTSクライアントの抽象基底クラス。
    """

    @abstractmethod
    async def synthesize_speech(self, text: str, speaker_id: Optional[Any] = None, **kwargs: Any) -> Optional[bytes]:
        """
        テキストから音声を合成します。

        Args:
            text (str): 音声に変換するテキスト。
            speaker_id (Optional[Any]): 使用する話者のID。エンジンによって型や意味が異なります。
            **kwargs (Any): エンジン固有の追加パラメータ。

        Returns:
            Optional[bytes]: 合成された音声データ (bytes形式)。失敗した場合はNone。
        """
        pass

    @abstractmethod
    async def check_availability(self) -> bool:
        """
        TTSエンジンが現在利用可能かどうかを確認します。

        Returns:
            bool: 利用可能な場合はTrue、そうでない場合はFalse。
        """
        pass
