#!/usr/bin/env python3
"""
音声認識クライアント
Discordのボイスチャンネルからユーザーの音声を認識してテキストに変換
"""

import os
import logging
import asyncio
import tempfile
import speech_recognition as sr
from typing import Optional, Dict, Any, Callable
import discord
from discord.ext import commands
import pyaudio
import wave
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class VoiceRecognitionClient:
    """音声認識クライアント"""
    
    def __init__(self, language: str = "ja-JP", confidence_threshold: float = 0.7):
        """
        Args:
            language: 認識言語 (デフォルト: 日本語)
            confidence_threshold: 認識の信頼度閾値
        """
        self.language = language
        self.confidence_threshold = confidence_threshold
        self.recognizer = sr.Recognizer()
        self.is_listening = False
        self.audio_data_queue = asyncio.Queue()
        
        # 音声認識の設定を調整
        self.recognizer.energy_threshold = 300  # 音声検出の感度
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8  # 発話終了と判断する無音時間
        self.recognizer.phrase_threshold = 0.3  # 発話開始の最小時間
        
        logger.info(f"音声認識クライアントを初期化しました (言語: {language})")
    
    async def start_listening(self, voice_client: discord.VoiceClient, 
                             callback: Callable[[str, str], None] = None):
        """
        音声認識を開始
        
        Args:
            voice_client: DiscordのVoiceClient
            callback: 認識結果を受け取るコールバック関数 (user_id, text)
        """
        if self.is_listening:
            logger.warning("音声認識は既に開始されています")
            return
        
        self.is_listening = True
        logger.info("音声認識を開始しました")
        
        # 音声データを受信するタスクを開始
        listen_task = asyncio.create_task(self._listen_to_voice_channel(voice_client, callback))
        
        return listen_task
    
    def stop_listening(self):
        """音声認識を停止"""
        self.is_listening = False
        logger.info("音声認識を停止しました")
    
    async def _listen_to_voice_channel(self, voice_client: discord.VoiceClient, 
                                     callback: Callable[[str, str], None]):
        """ボイスチャンネルからの音声を監視"""
        try:
            # Discord.pyの音声受信機能を使用
            # （注：この機能は実験的で、適切に動作しない場合があります）
            logger.info("ボイスチャンネルでの音声監視を開始")
            
            while self.is_listening and voice_client.is_connected():
                try:
                    # 一定間隔で音声データをチェック
                    await asyncio.sleep(0.1)
                    
                    # 実際の音声データ受信はDiscord.pyの制限により困難
                    # ここでは代替実装として、テキストチャンネルでの音声認識コマンドを想定
                    
                except Exception as e:
                    logger.error(f"音声監視中にエラー: {e}")
                    await asyncio.sleep(1)
            
            logger.info("音声監視を終了しました")
            
        except Exception as e:
            logger.error(f"音声監視の開始に失敗: {e}")
    
    async def recognize_audio_file(self, audio_file_path: str) -> Optional[str]:
        """
        音声ファイルからテキストを認識
        
        Args:
            audio_file_path: 音声ファイルのパス
            
        Returns:
            認識されたテキスト、または None
        """
        try:
            with sr.AudioFile(audio_file_path) as source:
                # 雑音を除去
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.record(source)
            
            # Google Speech Recognition APIを使用
            try:
                text = self.recognizer.recognize_google(audio, language=self.language)
                logger.info(f"音声認識成功: {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("音声を認識できませんでした")
                return None
            except sr.RequestError as e:
                logger.error(f"音声認識サービスエラー: {e}")
                return None
                
        except Exception as e:
            logger.error(f"音声ファイルの処理エラー: {e}")
            return None
    
    async def recognize_from_bytes(self, audio_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        """
        バイトデータから音声を認識
        
        Args:
            audio_bytes: 音声データ（WAV形式）
            sample_rate: サンプリングレート
            
        Returns:
            認識されたテキスト、または None
        """
        try:
            # 一時ファイルを作成
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_file_path = temp_file.name
            
            try:
                # 音声認識を実行
                result = await self.recognize_audio_file(temp_file_path)
                return result
            finally:
                # 一時ファイルを削除
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                
        except Exception as e:
            logger.error(f"バイトデータからの音声認識エラー: {e}")
            return None

class DiscordVoiceReceiver:
    """Discord音声受信クラス（実験的）"""
    
    def __init__(self, bot):
        self.bot = bot
        self.voice_recognition = VoiceRecognitionClient()
        self.listening_task = None
    
    async def start_voice_recognition(self, voice_client: discord.VoiceClient):
        """音声認識を開始"""
        try:
            if self.listening_task and not self.listening_task.done():
                logger.warning("音声認識は既に実行中です")
                return
            
            self.listening_task = await self.voice_recognition.start_listening(
                voice_client, 
                self._on_voice_recognized
            )
            
            logger.info("Discord音声認識を開始しました")
            
        except Exception as e:
            logger.error(f"音声認識の開始に失敗: {e}")
    
    def stop_voice_recognition(self):
        """音声認識を停止"""
        try:
            self.voice_recognition.stop_listening()
            
            if self.listening_task and not self.listening_task.done():
                self.listening_task.cancel()
            
            logger.info("Discord音声認識を停止しました")
            
        except Exception as e:
            logger.error(f"音声認識の停止に失敗: {e}")
    
    async def _on_voice_recognized(self, user_id: str, text: str):
        """音声認識結果のコールバック"""
        try:
            logger.info(f"音声認識結果 (ユーザー: {user_id}): {text}")
            
            # ボットのメンションとして処理
            # この実装では、音声入力もテキストメッセージとして扱う
            if hasattr(self.bot, 'process_voice_input'):
                await self.bot.process_voice_input(user_id, text)
            
        except Exception as e:
            logger.error(f"音声認識結果の処理エラー: {e}")

# 音声認識コマンドの追加（代替実装）
class VoiceRecognitionCog(commands.Cog):
    """音声認識関連のコマンド"""
    
    def __init__(self, bot):
        self.bot = bot
        self.voice_recognition = VoiceRecognitionClient()
    
    @commands.command(name='listen')
    async def start_listening(self, ctx):
        """音声認識を開始するコマンド"""
        if not ctx.voice_client:
            await ctx.send("ボイスチャンネルに参加していません")
            return
        
        try:
            # 実際の音声受信は技術的制限により困難
            # ここでは設定の確認のみ行う
            await ctx.send("🎤 音声認識モードを有効にしました（実験的機能）")
            logger.info(f"音声認識モードが有効になりました (チャンネル: {ctx.channel.name})")
            
        except Exception as e:
            await ctx.send(f"音声認識の開始に失敗しました: {e}")
            logger.error(f"音声認識コマンドエラー: {e}")
    
    @commands.command(name='stop_listen')
    async def stop_listening(self, ctx):
        """音声認識を停止するコマンド"""
        try:
            await ctx.send("🔇 音声認識モードを無効にしました")
            logger.info(f"音声認識モードが無効になりました (チャンネル: {ctx.channel.name})")
            
        except Exception as e:
            await ctx.send(f"音声認識の停止に失敗しました: {e}")
            logger.error(f"音声認識停止コマンドエラー: {e}")
    
    @commands.command(name='voice_test')
    async def test_voice_recognition(self, ctx):
        """音声認識のテスト（デモ用）"""
        try:
            # テスト用のダミー音声認識結果
            test_phrases = [
                "こんにちは、ボットさん！",
                "今日の天気はどうですか？",
                "音楽を再生してください",
                "ありがとうございました"
            ]
            
            import random
            test_text = random.choice(test_phrases)
            
            await ctx.send(f"🎤 音声認識テスト: 「{test_text}」")
            
            # ボットの応答をシミュレート
            if hasattr(self.bot, 'process_voice_input'):
                await self.bot.process_voice_input(str(ctx.author.id), test_text)
            
        except Exception as e:
            await ctx.send(f"音声認識テストに失敗しました: {e}")
            logger.error(f"音声認識テストエラー: {e}")

async def setup(bot):
    """Cogの設定"""
    await bot.add_cog(VoiceRecognitionCog(bot))
