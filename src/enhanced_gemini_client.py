#!/usr/bin/env python3
"""
強化されたGeminiクライアント
長期記憶データベースと統合し、より自然で文脈を理解した会話を提供
"""

import os
import logging
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image

# 長期記憶データベースのインポート
try:
    from .memory_database import MemoryDatabase
except ImportError:
    from memory_database import MemoryDatabase

logger = logging.getLogger(__name__)

class EnhancedMessageHistory:
    """強化されたメッセージ履歴管理"""
    
    def __init__(self, max_history_length: int = 15):
        self.history: List[Dict[str, Any]] = []
        self.max_history_length = max_history_length
    
    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """メッセージを履歴に追加（メタデータ付き）"""
        if len(self.history) >= self.max_history_length:
            self.history.pop(0)
        
        message = {
            "role": role,
            "parts": [{"text": content}],
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        self.history.append(message)
    
    def get_history_for_prompt(self) -> List[Dict[str, Any]]:
        """Gemini APIが期待する形式で履歴を返す"""
        return [{"role": msg["role"], "parts": msg["parts"]} for msg in self.history]
    
    def get_recent_context(self, message_count: int = 5) -> str:
        """最近の会話コンテキストを文字列として取得"""
        recent_messages = self.history[-message_count:] if self.history else []
        context_lines = []
        
        for msg in recent_messages:
            role = "ユーザー" if msg["role"] == "user" else "ボット"
            content = msg["parts"][0]["text"] if msg["parts"] else ""
            context_lines.append(f"{role}: {content}")
        
        return "\n".join(context_lines)
    
    def clear(self):
        """履歴をクリア"""
        self.history = []

class PersonalityAnalyzer:
    """ユーザーの性格や好みを分析するクラス"""
    
    @staticmethod
    def extract_facts_from_conversation(user_message: str, bot_response: str) -> List[Dict[str, str]]:
        """会話からユーザーの事実や好みを抽出"""
        facts = []
        
        # 好みの抽出パターン
        preference_patterns = [
            r"好き|嫌い|お気に入り|苦手",
            r"趣味|ホビー|興味",
            r"仕事|職業|学校",
            r"住んで|出身",
            r"年齢|歳"
        ]
        
        for pattern in preference_patterns:
            if re.search(pattern, user_message):
                facts.append({
                    'fact_type': 'preference',
                    'content': user_message.strip(),
                    'confidence_score': 0.6
                })
        
        return facts
    
    @staticmethod
    def analyze_emotion(message: str) -> Dict[str, float]:
        """メッセージの感情を簡易分析"""
        positive_words = ['嬉しい', 'ありがとう', '楽しい', '面白い', '良い', 'すごい', '好き']
        negative_words = ['悲しい', '辛い', '嫌', '困る', 'イライラ', '最悪', '嫌い']
        
        positive_score = sum(1 for word in positive_words if word in message)
        negative_score = sum(1 for word in negative_words if word in message)
        
        return {
            'positive': min(1.0, positive_score * 0.3),
            'negative': min(1.0, negative_score * 0.3),
            'neutral': max(0.0, 1.0 - (positive_score + negative_score) * 0.3)
        }

class EnhancedGeminiClient:
    """強化されたGeminiクライアント"""
    
    def __init__(
        self,
        api_key: str,
        model_name: str,
        project_root: str,
        character_name: str,
        character_config: Dict[str, Any],
        common_config: Dict[str, Any],
        memory_db_path: str = "data/memory.db"
    ):
        """
        Args:
            api_key: Gemini API key
            model_name: 使用するモデル名
            project_root: プロジェクトルートパス
            character_name: キャラクター名
            character_config: キャラクター固有の設定
            common_config: 共通設定
            memory_db_path: 長期記憶データベースのパス
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.project_root = project_root
        self.character_name = character_name
        self.character_config = character_config
        self.common_config = common_config
        
        # 長期記憶データベースの初期化
        self.memory_db = MemoryDatabase(memory_db_path)
        
        # 安全設定
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # 生成設定
        self.generation_config = genai.types.GenerationConfig(
            temperature=self.character_config.get("temperature", 0.8),
            top_p=self.character_config.get("top_p", 0.95),
            top_k=self.character_config.get("top_k", 40),
            max_output_tokens=self.character_config.get("max_output_tokens", 300),
        )
        
        # メッセージ履歴
        self.message_history = EnhancedMessageHistory(
            max_history_length=self.common_config.get("max_history_length", 15)
        )
        
        # プロンプト設定
        self.prompt_base_path = os.path.join(
            self.project_root, 
            self.common_config.get("prompt_base_path", "config/prompts")
        )
        
        # プロンプトファイルの読み込み
        self.system_prompt_template = self._load_prompt_file(
            self.character_config.get("system_prompt_template_file", "system_prompt_template.md")
        )
        self.character_personality = self._load_prompt_file(
            self.character_config.get("character_personality_file")
        )
        self.user_persona = self._load_prompt_file(
            self.character_config.get("user_persona_file")
        )
        
        # デフォルトプロンプトの設定
        self._set_default_prompts()
        
        # 性格分析器
        self.personality_analyzer = PersonalityAnalyzer()
        
        logger.info(f"Enhanced Gemini client initialized for character: {character_name}")
    
    def _load_prompt_file(self, file_name: Optional[str]) -> Optional[str]:
        """プロンプトファイルを読み込み"""
        if not file_name:
            return None
        
        try:
            file_path = os.path.join(self.prompt_base_path, file_name)
            normalized_path = os.path.normpath(file_path)
            
            if not normalized_path.startswith(os.path.normpath(self.project_root)):
                logger.error(f"Attempt to access file outside project root: {normalized_path}")
                return None
            
            with open(normalized_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            logger.info(f"Successfully loaded prompt file: {file_name}")
            return content
        
        except FileNotFoundError:
            logger.warning(f"Prompt file not found: {file_name}")
            return None
        except Exception as e:
            logger.error(f"Error loading prompt file {file_name}: {e}")
            return None
    
    def _set_default_prompts(self):
        """デフォルトプロンプトの設定"""
        if not self.system_prompt_template:
            self.system_prompt_template = """あなたは{character_name}というキャラクターです。
以下の特徴を持って会話してください：

{character_personality}

ユーザーとの関係性：
{user_relationship}

過去の会話から学んだ情報：
{learned_facts}

最近の会話の流れ：
{recent_context}

自然で一貫した性格を保ち、過去の会話を覚えているかのように振る舞ってください。
簡潔で親しみやすい返答を心がけてください。"""
        
        if not self.character_personality:
            self.character_personality = f"{self.character_name}は親切で知的なAIアシスタントです。"
        
        if not self.user_persona:
            self.user_persona = "ユーザーは親しみやすいDiscordユーザーです。"
    
    async def generate_response(
        self, 
        user_message: str, 
        discord_user_id: str, 
        username: str, 
        display_name: str = None,
        image: Optional[Image.Image] = None
    ) -> str:
        """強化された応答生成"""
        try:
            # ユーザー情報をデータベースに記録
            user = self.memory_db.get_or_create_user(discord_user_id, username, display_name)
            
            # 会話履歴をデータベースに追加
            self.memory_db.add_conversation(
                discord_user_id, self.character_name, 'user', user_message, 
                importance_score=self._calculate_importance_score(user_message)
            )
            
            # 長期記憶から情報を取得
            learned_facts = self.memory_db.get_learned_facts(discord_user_id, self.character_name)
            conversation_history = self.memory_db.get_conversation_history(
                discord_user_id, self.character_name, limit=10
            )
            user_stats = self.memory_db.get_user_stats(discord_user_id)
            
            # プロンプトを構築
            enhanced_prompt = self._build_enhanced_prompt(
                user_message, learned_facts, conversation_history, user_stats
            )
            
            # Gemini APIに送信
            if image:
                response = self.model.generate_content(
                    [enhanced_prompt, image],
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings
                )
            else:
                response = self.model.generate_content(
                    enhanced_prompt,
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings
                )
            
            bot_response = response.text if response.text else "すみません、うまく応答できませんでした。"
            
            # 応答をメモリに追加
            self.memory_db.add_conversation(
                discord_user_id, self.character_name, 'bot', bot_response
            )
            
            # メッセージ履歴に追加
            self.message_history.add_message("user", user_message)
            self.message_history.add_message("model", bot_response)
            
            # 新しい事実を学習
            self._learn_from_conversation(discord_user_id, user_message, bot_response)
            
            return bot_response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return f"すみません、{self.character_name}は今少し調子が悪いようです..."
    
    def _build_enhanced_prompt(
        self, 
        user_message: str, 
        learned_facts: List[Dict[str, Any]], 
        conversation_history: List[Dict[str, Any]], 
        user_stats: Dict[str, Any]
    ) -> str:
        """強化されたプロンプトを構築"""
        
        # 学習した事実をテキスト化
        facts_text = "特になし"
        if learned_facts:
            facts_lines = []
            for fact in learned_facts[:5]:  # 上位5つの事実
                confidence = fact['confidence_score']
                facts_lines.append(f"- {fact['content']} (信頼度: {confidence:.1f})")
            facts_text = "\n".join(facts_lines)
        
        # 最近の会話履歴をテキスト化
        recent_context = "初回の会話です"
        if conversation_history:
            context_lines = []
            for conv in conversation_history[-5:]:  # 最近の5件
                role = "ユーザー" if conv['message_type'] == 'user' else self.character_name
                context_lines.append(f"{role}: {conv['content']}")
            recent_context = "\n".join(context_lines)
        
        # ユーザーとの関係性を決定
        message_count = user_stats.get('total_messages', 0)
        if message_count < 5:
            relationship = "初対面または新しい知り合い"
        elif message_count < 20:
            relationship = "会話を始めたばかりの関係"
        else:
            relationship = "よく会話する親しい関係"
        
        # プロンプトを構築
        enhanced_prompt = self.system_prompt_template.format(
            character_name=self.character_name,
            character_personality=self.character_personality,
            user_relationship=relationship,
            learned_facts=facts_text,
            recent_context=recent_context
        )
        
        # 現在のメッセージを追加
        enhanced_prompt += f"\n\nユーザーからの新しいメッセージ: {user_message}\n\n{self.character_name}として自然に応答してください："
        
        return enhanced_prompt
    
    def _calculate_importance_score(self, message: str) -> float:
        """メッセージの重要度スコアを計算"""
        important_keywords = [
            '好き', '嫌い', '趣味', '仕事', '学校', '家族', '友達',
            '誕生日', '記念日', '大切', '重要', '秘密', '悩み'
        ]
        
        score = 0.0
        for keyword in important_keywords:
            if keyword in message:
                score += 0.2
        
        # 長いメッセージほど重要度が高い
        if len(message) > 50:
            score += 0.1
        if len(message) > 100:
            score += 0.1
        
        return min(1.0, score)
    
    def _learn_from_conversation(self, discord_user_id: str, user_message: str, bot_response: str):
        """会話から新しい事実を学習"""
        try:
            # 感情分析
            emotions = self.personality_analyzer.analyze_emotion(user_message)
            
            # 事実抽出
            facts = self.personality_analyzer.extract_facts_from_conversation(user_message, bot_response)
            
            # 学習した事実をデータベースに保存
            for fact in facts:
                self.memory_db.add_learned_fact(
                    discord_user_id,
                    self.character_name,
                    fact['fact_type'],
                    fact['content'],
                    fact['confidence_score']
                )
            
            logger.debug(f"Learned {len(facts)} facts from conversation with {discord_user_id}")
            
        except Exception as e:
            logger.error(f"Error learning from conversation: {e}")
    
    def get_user_summary(self, discord_user_id: str) -> Dict[str, Any]:
        """ユーザーのサマリー情報を取得"""
        try:
            stats = self.memory_db.get_user_stats(discord_user_id)
            facts = self.memory_db.get_learned_facts(discord_user_id, self.character_name)
            
            return {
                'stats': stats,
                'learned_facts': facts,
                'conversation_count': len(self.memory_db.get_conversation_history(
                    discord_user_id, self.character_name, limit=100
                ))
            }
        except Exception as e:
            logger.error(f"Error getting user summary: {e}")
            return {}
    
    def clear_session_history(self):
        """セッション履歴をクリア"""
        self.message_history.clear()
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """古いデータをクリーンアップ"""
        try:
            cleaned_count = self.memory_db.cleanup_old_conversations(days_to_keep)
            logger.info(f"Cleaned up {cleaned_count} old conversations")
            return cleaned_count
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0
