import os
import json
import logging
import random
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 強化されたGeminiクライアントのインポート
try:
    from .enhanced_gemini_client import EnhancedGeminiClient
    from .gemini_client import GeminiClient
except ImportError:
    from enhanced_gemini_client import EnhancedGeminiClient
    from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class CharacterManager:
    def __init__(self, config_path: str, use_enhanced_client: bool = True, memory_db=None): # memory_db パラメータを追加
        """
        キャラクター管理クラス
        
        Args:
            config_path: キャラクター設定ファイルのパス
            use_enhanced_client: 強化されたGeminiクライアントを使用するかどうか
            memory_db: メモリデータベースのインスタンス
        """
        self.characters = []
        self.use_enhanced_client = use_enhanced_client
        self.memory_db = memory_db # memory_db を属性として保存
        self.load_characters(config_path)
        self.conversation_history = []
        self.active_character = None
        self.last_character_switch = datetime.now()
        self.character_switch_interval = timedelta(seconds=30)
        
        # Geminiクライアントインスタンスのキャッシュ
        self.gemini_clients: Dict[str, Any] = {}
        
        logger.info(f"CharacterManager initialized with enhanced client: {use_enhanced_client}")
        
    def load_characters(self, config_path: str):
        """
        設定ファイルからキャラクターを読み込む
        
        Args:
            config_path: キャラクター設定ファイルのパス
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.characters = data.get('characters', [])
                logger.info(f"{len(self.characters)}人のキャラクターを読み込みました")
        except Exception as e:
            logger.error(f"キャラクター設定ファイルの読み込みエラー: {e}")
            raise
    
    def get_random_character(self, exclude=None):
        """
        ランダムなキャラクターを取得する（特定のキャラクターを除く）
        
        Args:
            exclude: 除外するキャラクター（オプション）
            
        Returns:
            ランダムに選ばれたキャラクター情報
        """
        available_characters = self.characters.copy()
        if exclude is not None:
            available_characters = [c for c in available_characters if c['name'] != exclude['name']]
        
        if not available_characters:
            return random.choice(self.characters)
        
        return random.choice(available_characters)
    
    def should_switch_character(self):
        """
        キャラクターを切り替えるべきかを判断する
        
        Returns:
            True: キャラクターを切り替えるべき場合
            False: それ以外の場合
        """
        now = datetime.now()
        return (now - self.last_character_switch) > self.character_switch_interval
    
    def switch_character(self):
        """
        発言するキャラクターを切り替える
        
        Returns:
            新しく選ばれたキャラクター情報
        """
        new_character = self.get_random_character(exclude=self.active_character)
        self.active_character = new_character
        self.last_character_switch = datetime.now()
        logger.info(f"キャラクターを切り替え: {new_character['name']}")
        return new_character
    
    def get_active_character(self):
        """
        現在アクティブなキャラクターを取得する
        初めて呼ばれた場合はランダムに選択する
        
        Returns:
            現在アクティブなキャラクター情報
        """
        if self.active_character is None or self.should_switch_character():
            return self.switch_character()
        return self.active_character
    
    def record_conversation(self, speaker: str, text: str):
        """
        会話履歴に追加する
        
        Args:
            speaker: 発言者の名前
            text: 発言内容
        """
        self.conversation_history.append({
            'speaker': speaker,
            'text': text,
            'timestamp': datetime.now().isoformat()
        })
        
        # 履歴が長すぎる場合は古いものを削除
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
    
    def get_conversation_history(self):
        """
        会話履歴を取得する
        
        Returns:
            会話履歴のリスト
        """
        return self.conversation_history
    
    def create_gemini_client(self, character: Dict[str, Any], project_root: str, 
                           common_config: Dict[str, Any]) -> Optional[Any]:
        """
        キャラクター用のGeminiクライアントを作成
        
        Args:
            character: キャラクター情報
            project_root: プロジェクトルートパス  
            common_config: 共通設定
            
        Returns:
            作成されたGeminiクライアント、またはNone
        """
        try:
            character_name = character['name']
            
            # 既にクライアントが存在する場合は再利用
            if character_name in self.gemini_clients:
                return self.gemini_clients[character_name]
            
            # 環境変数からAPIキーを取得
            api_key_env = character.get('gemini_api_key_env', 'GEMINI_API_KEY')
            api_key = os.getenv(api_key_env)
            
            if not api_key:
                logger.warning(f"Gemini API key not found for character {character_name}")
                return None
            
            model_name = character.get('model_name', 'gemini-1.5-flash')
            
            # 強化クライアントまたは通常クライアントを作成
            if self.use_enhanced_client:
                client = EnhancedGeminiClient(
                    api_key=api_key,
                    model_name=model_name,
                    project_root=project_root,
                    character_name=character_name,
                    character_config=character,
                    common_config=common_config,
                    memory_db_path=f"data/memory_{character_name.lower()}.db"
                )
            else:
                client = GeminiClient(
                    api_key=api_key,
                    model_name=model_name,
                    project_root=project_root,
                    character_name=character_name,
                    character_config=character,
                    common_config=common_config
                )
            
            # クライアントをキャッシュ
            self.gemini_clients[character_name] = client
            
            logger.info(f"Created {'enhanced' if self.use_enhanced_client else 'standard'} "
                       f"Gemini client for {character_name}")
            
            return client
            
        except Exception as e:
            logger.error(f"Failed to create Gemini client for {character['name']}: {e}")
            return None
    
    def get_gemini_client(self, character_name: str) -> Optional[Any]:
        """
        キャラクター名でGeminiクライアントを取得
        
        Args:
            character_name: キャラクター名
            
        Returns:
            Geminiクライアント、またはNone
        """
        return self.gemini_clients.get(character_name)
    
    def cleanup_old_memories(self, days_to_keep: int = 30):
        """
        全キャラクターの古い記憶をクリーンアップ
        
        Args:
            days_to_keep: 保持する日数
        """
        if not self.use_enhanced_client:
            logger.info("Enhanced client not enabled, skipping memory cleanup")
            return
        
        total_cleaned = 0
        for character_name, client in self.gemini_clients.items():
            if hasattr(client, 'cleanup_old_data'):
                try:
                    cleaned = client.cleanup_old_data(days_to_keep)
                    total_cleaned += cleaned
                    logger.info(f"Cleaned {cleaned} old records for {character_name}")
                except Exception as e:
                    logger.error(f"Error cleaning data for {character_name}: {e}")
        
        logger.info(f"Total cleaned records: {total_cleaned}")
    
    def get_character_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        名前でキャラクターを取得
        
        Args:
            name: キャラクター名
            
        Returns:
            キャラクター情報、またはNone
        """
        for character in self.characters:
            if character['name'] == name:
                return character
        return None