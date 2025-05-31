# このファイルはsrcディレクトリをPythonパッケージとして認識させるためのものです

"""
AI Chatbot パッケージ

このパッケージには Discord ボット、TTS クライアント、キャラクター管理、
および Gemini AI との連携機能が含まれています。
"""

__version__ = "1.0.0"
__author__ = "AI Chatbot Team"

# 主要なモジュールをインポートして利用しやすくする
try:
    from .character_manager import CharacterManager
    from .discord_bot import CharacterBot, run_bots
    
    # TTS関連
    from .tts_clients.tts_factory import TTSClientFactory
    from .tts_clients.dummy_tts_client import DummyTTSClient
    from .tts_clients.abstract_tts_client import AbstractTTSClient
    
    # Gemini関連（オプション）
    try:
        from .gemini_client import GeminiClient
        GEMINI_AVAILABLE = True
    except ImportError:
        GEMINI_AVAILABLE = False
        GeminiClient = None
    
    __all__ = [
        'CharacterManager',
        'CharacterBot', 
        'run_bots',
        'TTSClientFactory',
        'DummyTTSClient', 
        'AbstractTTSClient',
        'GeminiClient',
        'GEMINI_AVAILABLE'
    ]
    
except ImportError as e:
    # インポートエラーが発生した場合はログに記録
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Some modules could not be imported: {e}")
    
    __all__ = []