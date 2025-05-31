import os
import io
import logging
import time
from typing import Optional, Any, Dict

import httpx
import asyncio

from .abstract_tts_client import AbstractTTSClient

logger = logging.getLogger("src.discord_bot") # discord_bot.py と同じロガー名を使用

class VoicevoxClient(AbstractTTSClient):
    """
    VOICEVOXエンジンと通信するためのクライアント。
    AbstractTTSClientを実装します。
    """
    def __init__(self, base_url: str = "http://127.0.0.1:50021", timeout: int = 30):
        """
        VoicevoxClientを初期化します。

        Args:
            base_url (str): VOICEVOXエンジンのベースURL (例: "http://localhost:50021")。
            timeout (int): APIリクエストのタイムアウト秒数。
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # より長いタイムアウトと再試行を設定
        self.client = httpx.AsyncClient(
            base_url=self.base_url, 
            timeout=httpx.Timeout(timeout, read=timeout),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2)
        )
        logger.info(f"VoicevoxClient initialized with base_url: {self.base_url}, timeout: {self.timeout}", extra={"bot_name": "System"})
        self.default_speaker_id = 3  # ずんだもんのデフォルト話者ID

    async def _make_request(self, method: str, endpoint: str, **kwargs: Any) -> Optional[httpx.Response]:
        """
        VOICEVOXエンジンにリクエストを送信します。
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status() # HTTPエラーがあれば例外を発生
            return response
        except httpx.TimeoutException:
            logger.error(f"Request to {url} timed out after {self.timeout} seconds.")
        except httpx.RequestError as e:
            logger.error(f"Request to {url} failed: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred while requesting {url}: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during request to {url}: {e}", exc_info=True)
        return None

    async def synthesize_speech(self, text: str, speaker_id: Optional[Any] = None, **kwargs: Any) -> Optional[bytes]:
        """
        指定されたテキストと話者IDを使用して音声を合成します。
        kwargs はVOICEVOXの audio_query と synthesis APIの追加パラメータを想定します。
        """
        actual_speaker_id = speaker_id if speaker_id is not None else self.default_speaker_id
        if not isinstance(actual_speaker_id, int):
            try:
                actual_speaker_id = int(actual_speaker_id)
            except ValueError:
                logger.error(f"Invalid speaker_id format: {speaker_id}. Must be an integer. Using default: {self.default_speaker_id}")
                actual_speaker_id = self.default_speaker_id

        logger.info(f"Synthesizing speech for text: \"{text[:30]}...\" with speaker_id: {actual_speaker_id}", extra={"bot_name": "System"})

        # 1. audio_queryの作成
        query_params = {"text": text, "speaker": actual_speaker_id}
        # kwargs から audio_query に関連するパラメータを抽出・追加 (例: speedScale, pitchScaleなど)
        # ここでは簡単のため、直接的なパラメータは指定しないが、拡張可能
        query_response = await self._make_request("POST", "audio_query", params=query_params)
        if not query_response:
            logger.error("Failed to create audio query.")
            return None
        
        audio_query_data = query_response.json()

        # kwargs から synthesis に関連するパラメータを抽出・上書き
        # (例: enable_interrogative_upspeak)
        # audio_query_data.update({k: v for k, v in kwargs.items() if k in audio_query_data})
        if "speedScale" in kwargs and isinstance(kwargs["speedScale"], (int, float)):
            audio_query_data["speedScale"] = kwargs["speedScale"]
        if "pitchScale" in kwargs and isinstance(kwargs["pitchScale"], (int, float)):
            audio_query_data["pitchScale"] = kwargs["pitchScale"]
        # 他のパラメータも同様に追加可能

        # 2. 音声合成
        synthesis_params = {"speaker": actual_speaker_id}
        # kwargs から synthesis API に関連するパラメータを抽出・追加
        # (例: enable_interrogative_upspeak)
        # synthesis_params.update({k:v for k,v in kwargs.items() if k == "enable_interrogative_upspeak"})

        synthesis_response = await self._make_request(
            "POST", 
            "synthesis", 
            params=synthesis_params, 
            json=audio_query_data, # audio_queryの結果をJSONボディとして送信
            headers={"Content-Type": "application/json", "Accept": "audio/wav"}
        )

        if not synthesis_response:
            logger.error("Failed to synthesize speech.")
            return None

        logger.info(f"Speech synthesized successfully for speaker_id: {actual_speaker_id}", extra={"bot_name": "System"})
        return synthesis_response.content

    async def get_speakers(self) -> Optional[list]:
        """
        利用可能な話者のリストを取得します。
        """
        response = await self._make_request("GET", "speakers")
        return response.json() if response else None

    async def check_availability(self) -> bool:
        """
        VOICEVOXエンジンが利用可能か（疎通確認）を確認します。
        ルートエンドポイント ("/") や "version" エンドポイントを試すことが多い。
        """
        try:
            # "version" エンドポイントが存在すればそれを使うのが一般的
            # ここでは、単純にルートへのGETリクエストで確認
            response = await self.client.get(f"{self.base_url}/version", timeout=2) # 短めのタイムアウトで確認
            response.raise_for_status()
            logger.info(f"Voicevox engine at {self.base_url} is available.", extra={"bot_name": "System"})
            return True
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"Voicevox engine at {self.base_url} is unavailable: {e}", extra={"bot_name": "System"})
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking Voicevox availability: {e}", exc_info=True, extra={"bot_name": "System"})
            return False

    async def close(self):
        """
        HTTPクライアントをクローズします。
        """
        await self.client.aclose()
        logger.info("VoicevoxClient closed.", extra={"bot_name": "System"})

    async def text_to_speech_parallel(self, text: str, speaker_id: int = None, output_dir: str = "temp_audio") -> str:
        """
        テキストを音声合成し、音声ファイルのパスを返します。

        Args:
            text (str): 音声に変換するテキスト
            speaker_id (int, optional): 使用する話者のID。デフォルトはNone（初期化時のデフォルト値が使用される）
            output_dir (str, optional): 出力ディレクトリ。デフォルトは"temp_audio"

        Returns:
            str: 生成された音声ファイルのパス（失敗時はNone）
        """
        # 出力ディレクトリが存在しない場合は作成
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # テキスト全体を一度に処理
            return await self._process_single_text(text, speaker_id, output_dir, 0)
        except Exception as e:
            logger.error(f"音声合成中にエラーが発生しました: {e}")
            return None

    async def _process_single_text(self, text: str, speaker_id: int, output_dir: str, index: int) -> str:
        """
        単一のテキストを処理し、音声ファイルを生成します。

        Args:
            text (str): 音声に変換するテキスト
            speaker_id (int): 使用する話者のID
            output_dir (str): 出力ディレクトリ
            index (int): ファイル名のインデックス

        Returns:
            str: 生成された音声ファイルのパス
        """
        try:
            # テキストから音声を合成
            audio_data = await self.synthesize_speech(text, speaker_id)
            
            if audio_data:
                # 一意なファイル名を生成
                timestamp = int(time.time())
                filename = f"{output_dir}/speech_{timestamp}_{index}.wav"
                
                # 音声データをファイルに書き込み
                with open(filename, "wb") as f:
                    f.write(audio_data)
                    
                logger.info(f"音声ファイルを生成しました: {filename}", extra={"bot_name": "System"})
                return filename
                
        except Exception as e:
            logger.error(f"音声処理中にエラーが発生しました: {e}", exc_info=True)
            raise
            
        return None