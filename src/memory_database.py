#!/usr/bin/env python3
"""
長期記憶データベースモジュール
SQLAlchemyを使用してユーザーとの会話履歴、学習したパーソナリティ、
重要なイベントなどを永続化するシステム
"""

import os
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    """ユーザー情報テーブル"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    discord_user_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100), nullable=False)
    display_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    personality_notes = Column(Text)  # ユーザーの性格や好みのメモ
    
    # リレーション
    conversations = relationship("Conversation", back_populates="user")
    learned_facts = relationship("LearnedFact", back_populates="user")

class Conversation(Base):
    """会話履歴テーブル"""
    __tablename__ = 'conversations'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    character_name = Column(String(50), nullable=False)
    message_type = Column(String(20), nullable=False)  # 'user', 'bot'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    emotion_score = Column(Float)  # 感情スコア（将来の実装用）
    importance_score = Column(Float, default=0.0)  # 重要度スコア
    
    # リレーション
    user = relationship("User", back_populates="conversations")

class LearnedFact(Base):
    """学習した事実・パーソナリティテーブル"""
    __tablename__ = 'learned_facts'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    character_name = Column(String(50), nullable=False)
    fact_type = Column(String(50), nullable=False)  # 'preference', 'hobby', 'personality', 'fact'
    content = Column(Text, nullable=False)
    confidence_score = Column(Float, default=0.5)  # 信頼度スコア
    learned_date = Column(DateTime, default=datetime.utcnow)
    last_reinforced = Column(DateTime, default=datetime.utcnow)
    reinforcement_count = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    
    # リレーション
    user = relationship("User", back_populates="learned_facts")

class MemoryDatabase:
    """長期記憶データベース管理クラス"""
    
    def __init__(self, db_path: str = "data/memory.db"):
        """
        Args:
            db_path: SQLiteデータベースファイルのパス
        """
        self.db_path = db_path
        self.ensure_data_directory()
        
        # SQLiteデータベースエンジンを作成
        self.engine = create_engine(f'sqlite:///{self.db_path}', echo=False)
        Base.metadata.create_all(self.engine)
        
        # セッションファクトリーを作成
        self.Session = sessionmaker(bind=self.engine)
        
        logger.info(f"Memory database initialized: {self.db_path}")
    
    def ensure_data_directory(self):
        """データディレクトリが存在することを確認"""
        data_dir = os.path.dirname(self.db_path)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"Created data directory: {data_dir}")
    
    def get_or_create_user(self, discord_user_id: str, username: str, display_name: str = None) -> User:
        """ユーザーを取得または作成"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                user = User(
                    discord_user_id=discord_user_id,
                    username=username,
                    display_name=display_name or username
                )
                session.add(user)
                session.commit()
                session.refresh(user)
                logger.info(f"Created new user: {username} ({discord_user_id})")
            else:
                # 既存ユーザーの情報を更新
                user.username = username
                user.display_name = display_name or username
                user.last_seen = datetime.utcnow()
                session.commit()
            
            return user
    
    def add_conversation(self, discord_user_id: str, character_name: str, 
                        message_type: str, content: str, importance_score: float = 0.0) -> None:
        """会話履歴を追加"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                logger.warning(f"User not found for conversation: {discord_user_id}")
                return
            
            conversation = Conversation(
                user_id=user.id,
                character_name=character_name,
                message_type=message_type,
                content=content,
                importance_score=importance_score
            )
            
            session.add(conversation)
            
            # ユーザーのメッセージカウントを更新
            if message_type == 'user':
                user.message_count += 1
            
            session.commit()
    
    def get_conversation_history(self, discord_user_id: str, character_name: str, 
                               limit: int = 20, days_back: int = 7) -> List[Dict[str, Any]]:
        """指定した期間の会話履歴を取得"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                return []
            
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            
            conversations = session.query(Conversation).filter(
                Conversation.user_id == user.id,
                Conversation.character_name == character_name,
                Conversation.timestamp >= cutoff_date
            ).order_by(Conversation.timestamp.desc()).limit(limit).all()
            
            return [
                {
                    'message_type': conv.message_type,
                    'content': conv.content,
                    'timestamp': conv.timestamp.isoformat(),
                    'importance_score': conv.importance_score
                }
                for conv in reversed(conversations)  # 時系列順に並び替え
            ]
    
    def add_learned_fact(self, discord_user_id: str, character_name: str,
                        fact_type: str, content: str, confidence_score: float = 0.5) -> None:
        """学習した事実を追加"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                logger.warning(f"User not found for learned fact: {discord_user_id}")
                return
            
            # 既存の類似した事実をチェック
            existing_fact = session.query(LearnedFact).filter(
                LearnedFact.user_id == user.id,
                LearnedFact.character_name == character_name,
                LearnedFact.fact_type == fact_type,
                LearnedFact.content == content,
                LearnedFact.is_active == True
            ).first()
            
            if existing_fact:
                # 既存の事実を強化
                existing_fact.confidence_score = min(1.0, existing_fact.confidence_score + 0.1)
                existing_fact.last_reinforced = datetime.utcnow()
                existing_fact.reinforcement_count += 1
            else:
                # 新しい事実を追加
                fact = LearnedFact(
                    user_id=user.id,
                    character_name=character_name,
                    fact_type=fact_type,
                    content=content,
                    confidence_score=confidence_score
                )
                session.add(fact)
            
            session.commit()
    
    def get_learned_facts(self, discord_user_id: str, character_name: str,
                         fact_type: str = None, min_confidence: float = 0.3) -> List[Dict[str, Any]]:
        """学習した事実を取得"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                return []
            
            query = session.query(LearnedFact).filter(
                LearnedFact.user_id == user.id,
                LearnedFact.character_name == character_name,
                LearnedFact.confidence_score >= min_confidence,
                LearnedFact.is_active == True
            )
            
            if fact_type:
                query = query.filter(LearnedFact.fact_type == fact_type)
            
            facts = query.order_by(LearnedFact.confidence_score.desc()).all()
            
            return [
                {
                    'fact_type': fact.fact_type,
                    'content': fact.content,
                    'confidence_score': fact.confidence_score,
                    'learned_date': fact.learned_date.isoformat(),
                    'reinforcement_count': fact.reinforcement_count
                }
                for fact in facts
            ]
    
    def update_user_personality_notes(self, discord_user_id: str, notes: str) -> None:
        """ユーザーの性格メモを更新"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if user:
                user.personality_notes = notes
                session.commit()
    
    def get_user_stats(self, discord_user_id: str) -> Dict[str, Any]:
        """ユーザーの統計情報を取得"""
        with self.Session() as session:
            user = session.query(User).filter(User.discord_user_id == discord_user_id).first()
            
            if not user:
                return {}
            
            # 最近の会話数
            recent_conversations = session.query(Conversation).filter(
                Conversation.user_id == user.id,
                Conversation.timestamp >= datetime.utcnow() - timedelta(days=7)
            ).count()
            
            # 学習した事実数
            learned_facts_count = session.query(LearnedFact).filter(
                LearnedFact.user_id == user.id,
                LearnedFact.is_active == True
            ).count()
            
            return {
                'username': user.username,
                'display_name': user.display_name,
                'total_messages': user.message_count,
                'recent_conversations': recent_conversations,
                'learned_facts_count': learned_facts_count,
                'first_seen': user.created_at.isoformat(),
                'last_seen': user.last_seen.isoformat(),
                'personality_notes': user.personality_notes
            }
    
    def cleanup_old_conversations(self, days_to_keep: int = 30) -> int:
        """古い会話履歴をクリーンアップ"""
        with self.Session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            deleted_count = session.query(Conversation).filter(
                Conversation.timestamp < cutoff_date,
                Conversation.importance_score < 0.5  # 重要度の低いもののみ削除
            ).delete()
            
            session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old conversations")
            
            return deleted_count
    
    def update_bot_state(self, bot_id: str, is_active: bool, activity_rate: float) -> None:
        """ボットの状態を更新（BotActivityManagerから呼び出される）"""
        try:
            # ここでは実際のデータベース更新は行わず、ログ出力のみ
            # 必要に応じて後でボット状態テーブルを追加可能
            logger.debug(f"Bot {bot_id} state update: active={is_active}, rate={activity_rate:.2f}")
        except Exception as e:
            logger.error(f"Error updating bot state for bot {bot_id}: {e}")
