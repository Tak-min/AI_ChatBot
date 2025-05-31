import os
import json
import logging
import asyncio
import random
import discord
import tempfile
import threading
import time
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv

# インポートの修正（相対インポートと絶対インポートの両方をサポート）
try:
    from .tts_clients import TTSClientFactory
    from .tts_clients.dummy_tts_client import DummyTTSClient
    from .character_manager import CharacterManager
    from .voice_recognition import VoiceRecognitionClient, DiscordVoiceReceiver
    from .performance_optimizer import OptimizedBot, AsyncTaskManager, PerformanceMonitor
    from .bot_activity_manager import BotActivityManager, ActivityMode, MoodState
    from .memory_database import MemoryDatabase
except ImportError:
    # テストファイルからの直接インポート用
    from tts_clients import TTSClientFactory
    from tts_clients.dummy_tts_client import DummyTTSClient
    from character_manager import CharacterManager
    from voice_recognition import VoiceRecognitionClient, DiscordVoiceReceiver
    from performance_optimizer import OptimizedBot, AsyncTaskManager, PerformanceMonitor
    from bot_activity_manager import BotActivityManager, ActivityMode, MoodState
    from memory_database import MemoryDatabase

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 環境変数の読み込み
load_dotenv()

try:
    # 相対インポートを最初に試行
    try:
        from .gemini_client import GeminiClient
    except ImportError:
        # テストファイルからの直接インポート用
        from gemini_client import GeminiClient
    GEMINI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Gemini client could not be imported: {e}")
    GEMINI_AVAILABLE = False
    GeminiClient = None

# Discord botの設定
# 特権インテントが有効化されているか確認するための環境変数
USE_PRIVILEGED_INTENTS = os.getenv("USE_PRIVILEGED_INTENTS", "True").lower() == "true"

# 設定情報
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
TARGET_USER_ID = int(os.getenv("TARGET_USER_ID", 0))
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", 0))
TEXT_CHANNEL_ID = int(os.getenv("TEXT_CHANNEL_ID", 0))
BOT_COUNT = int(os.getenv("BOT_COUNT", 1))  # 同時起動するボットの数

# ボットトークンの処理を改善
raw_tokens = os.getenv("BOT_TOKENS", "")
BOT_TOKENS = []
if raw_tokens:
    # カンマで区切り、空のトークンを除外
    for token in raw_tokens.split(","):
        if token.strip():
            BOT_TOKENS.append(token.strip())

# メインのDISCORD_TOKENがある場合は、それも含める
if DISCORD_TOKEN and DISCORD_TOKEN not in BOT_TOKENS:
    BOT_TOKENS.append(DISCORD_TOKEN)

# トークンがない場合のエラー表示
if not BOT_TOKENS:
    logger.error("有効なボットトークンが設定されていません。BOT_TOKENSかDISCORD_TOKENを環境変数に設定してください。")

# 設定ファイルの読み込み
def load_config():
    """設定ファイルを読み込む"""
    import json
    from pathlib import Path
    
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"設定ファイルが見つかりません: {config_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"設定ファイルの読み込みエラー: {e}")
        return {}

# 設定の読み込み
config = load_config()

# カスタムBotクラスの定義
class CharacterBot(OptimizedBot, commands.Bot):
    def __init__(self, bot_id, character_config=None):
        # インテントの設定
        intents = discord.Intents.default()
        if USE_PRIVILEGED_INTENTS:
            # 特権インテントを使用する場合（Discord Developer Portalで有効化する必要あり）
            logger.info("特権インテントを使用します。Discord Developer Portalで有効化されていることを確認してください。")
            intents.presences = True  # プレゼンス情報の取得許可
            intents.message_content = True  # メッセージ内容の取得許可
            intents.members = True  # メンバー情報の取得許可
        else:
            # 特権インテントを使用しない場合（機能が制限されます）
            logger.warning("特権インテントを使用しません。一部の機能が制限されます。")
            intents.presences = False
            intents.message_content = False
            intents.members = False

        intents.voice_states = True  # ボイスチャンネル状態の取得許可（これは特権インテントではない）
          # 両方の親クラスを適切に初期化
        commands.Bot.__init__(self, command_prefix='!', intents=intents)
        OptimizedBot.__init__(self)
        
        # ボットの識別子とリソースを設定
        self.bot_id = bot_id
        self.character_config = character_config
        
        # 設定ファイルの読み込み
        self.config = load_config()
        
        # メモリデータベースの初期化
        self.memory_db = MemoryDatabase()
        
        # 強化されたキャラクターマネージャーを初期化
        self.character_manager = CharacterManager(
            "config/characters.json", 
            use_enhanced_client=True,  # 強化されたGeminiクライアントを使用
            memory_db=self.memory_db
        )
          # ボット活動マネージャーの初期化
        self.activity_manager = BotActivityManager(
            config=self.config.get('activity_settings', {}),
            bot_id=bot_id,
            memory_db=self.memory_db
        )
        
        self.audio_queue = asyncio.Queue()
        self.voice_client = None
        self.is_speaking = False
        self.random_talk_cooldown = datetime.now()
        self.text_chat_cooldown = datetime.now()
        self.character = None
        
        # TTSクライアントとGeminiクライアントの初期化（on_readyで実行）
        self.tts_client = None  # on_readyで初期化される
        
        # Geminiクライアントは各キャラクターに対して個別に初期化される
        self.gemini_client = None  # 現在アクティブなキャラクターのGeminiクライアント
        
        # 音声認識クライアントの初期化
        self.voice_receiver = DiscordVoiceReceiver(self)
        self.voice_recognition_enabled = False
          # イベントハンドラを登録
        self.setup_events()
        
    def setup_events(self):
        # on_ready イベント
        @self.event
        async def on_ready():
            logger.info(f"Bot {self.bot_id} が {self.user.name} としてログインしました!")
            # TTSクライアントの初期化
            logger.info(f"Bot {self.bot_id} ({self.user.name}): TTSクライアントの初期化を開始します...")
            try:
                tts_config = self.config.get('tts_settings', {})
                engine_name = tts_config.get('engine', 'voicevox')
                logger.info(f"Bot {self.bot_id}: TTSエンジン '{engine_name}' で初期化を試行します")
                
                self.tts_client = await TTSClientFactory.create_tts_client(engine_name, tts_config, enable_fallback=True)
                logger.info(f"Bot {self.bot_id}: TTSクライアント ({type(self.tts_client).__name__}) が正常に初期化されました")
                
            except Exception as e:
                logger.error(f"Bot {self.bot_id}: TTSクライアントの初期化に失敗しました: {e}")
                # 直接DummyTTSClientを作成してフォールバック
                try:
                    self.tts_client = DummyTTSClient()
                    logger.info(f"Bot {self.bot_id}: DummyTTSClientにフォールバックしました")
                except Exception as fallback_error:
                    logger.critical(f"Bot {self.bot_id}: フォールバックも失敗しました: {fallback_error}")
                    self.tts_client = None
            
            # キャラクターの割り当て
            if not self.character:
                assigned_characters = [bot.character for bot in bots if bot.character]
                
                available_characters = [c for c in self.character_manager.characters 
                                     if c['name'] not in [ac['name'] for ac in assigned_characters if ac]]
                
                if not available_characters:
                    available_characters = self.character_manager.characters
                    
                self.character = random.choice(available_characters)
                logger.info(f"Bot {self.bot_id} に {self.character['name']} を割り当てました")
                
                # キャラクターが決まったらGeminiクライアントを初期化
                await self.initialize_gemini_client()                # タスクを初期化
            if self.bot_id == 0:  # メインボット（0番）だけが状態監視を行う
                self.user_status_task = check_user_status
                if not self.user_status_task.is_running():
                    self.user_status_task.start(self)
                
            # 全てのボットが以下のタスクを実行
            self.process_audio_queue_task = tasks.loop(seconds=1.0)(self.process_audio_queue)
            self.random_voice_chat_task = tasks.loop(seconds=5.0)(self.random_voice_chat)
            
            # configから設定を読み込む
            config = load_config()
            random_text_chat_config = config.get("bot_activity", {}).get("random_text_chat", {})
            
            if random_text_chat_config.get("enabled", True):
                check_interval = random_text_chat_config.get("check_interval_seconds", 15.0)
                self.random_text_chat_task = tasks.loop(seconds=check_interval)(self.random_text_chat)
                logger.info(f"ランダムテキストチャット機能が有効化されました (チェック間隔: {check_interval}秒)")
            else:
                self.random_text_chat_task = None
                
            # デフォルトではタスクを開始（アクティビティマネージャーで管理されるため）
            await self.enable_tasks()
              # 管理ループを開始
            asyncio.create_task(self.start_management_loop())
            
            # アクティビティマネージャーに自身を登録
            await self.activity_manager.register_bot(str(self.bot_id), self)
            
    async def enable_tasks(self):
        """ボットのタスクを有効化する（オンライン時）"""
        try:
            if self.process_audio_queue_task and not self.process_audio_queue_task.is_running():
                self.process_audio_queue_task.start()
                
            if self.random_voice_chat_task and not self.random_voice_chat_task.is_running():
                self.random_voice_chat_task.start()
                
            if self.random_text_chat_task and not self.random_text_chat_task.is_running():
                self.random_text_chat_task.start()
                
            logger.info(f"Bot {self.bot_id} のタスクを有効化しました")
        except Exception as e:
            logger.error(f"タスク有効化中にエラー: {e}")
    
    async def disable_tasks(self):
        """ボットのタスクを無効化する（オフライン時）"""
        try:
            if hasattr(self, 'process_audio_queue_task') and self.process_audio_queue_task.is_running():
                self.process_audio_queue_task.cancel()
                
            if hasattr(self, 'random_voice_chat_task') and self.random_voice_chat_task.is_running():
                self.random_voice_chat_task.cancel()
                
            if hasattr(self, 'random_text_chat_task') and self.random_text_chat_task and self.random_text_chat_task.is_running():
                self.random_text_chat_task.cancel()
                
            logger.info(f"Bot {self.bot_id} のタスクを無効化しました")
        except Exception as e:
            logger.error(f"タスク無効化中にエラー: {e}")
    
    async def start_management_loop(self):
        """ボットのステータス管理ループを起動"""
        await asyncio.sleep(10)  # 起動時に少し待つ
        
        while True:
            try:
                # ステータスチェックなど
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"ボット管理ループエラー: {e}")
                await asyncio.sleep(30)
          # on_message イベント        @self.event
        async def on_message(self, message: discord.Message):
            # 自分のメッセージには反応しない
            # logger.debug(f"Message from {message.author}: {message.content}")
            if message.author == self.user:
                return

            # ボットがアクティブかどうか、およびランダムテキストチャットタスクが実行中かどうかを確認します。
            # この行は `bots` 変数が定義されている場所に移動するか、`bots` を取得する方法を修正する必要があります。
            # active_bots = [b for b_id, b_state in self.activity_manager.bot_states.items() if b_state.is_active and bots[int(b_id)].random_text_chat_task.is_running()]

            # オフライン時は応答しない（アクティビティマネージャーで管理）
            if str(self.bot_id) in self.activity_manager.bot_states:
                state = self.activity_manager.bot_states[str(self.bot_id)]
                if not state.is_active:
                    return
            
            # ユーザーからのメンション
            if self.user.mentioned_in(message):
                if not self.gemini_client:
                    logger.error("GeminiClientが初期化されていません")
                    await message.channel.send("すみません、現在応答システムが利用できません。")
                    return
                
                try:
                    character = self.character
                    
                    # 強化されたGeminiクライアントを使用
                    if hasattr(self.gemini_client, 'generate_response'):
                        # 強化されたクライアントの場合
                        user_id_str = str(message.author.id)
                        character_name = character['name']
                        channel_id_str = str(message.channel.id)
                        user_text_content = message.content
                        # logger.info(f"Received message from {message.author.name} ({user_id_str}) for {character_name} in channel {channel_id_str}: {user_text_content}")
                        # self.performance_optimizer.log_memory_usage(f"Before Gemini call for {character_name}")

                        if hasattr(self.gemini_client, 'memory_db') and self.gemini_client.memory_db is not None: # EnhancedGeminiClient
                            logger.debug(f"Using EnhancedGeminiClient for {character_name}")
                            response_text = await self.gemini_client.generate_response(
                                user_text_content,
                                user_id_str,
                                character_name,
                                channel_id_str,
                                message.attachments  # Pass attachments
                            )
                        elif hasattr(self.gemini_client, 'generate_response'): # Older GeminiClient
                            logger.debug(f"Using standard GeminiClient for {character_name}")
                            response_text = await self.gemini_client.generate_response(
                                user_text_content,
                                user_id_str,
                                character_name,
                                channel_id_str
                            )
                        else:
                            logger.error(f"Gemini client for {character_name} is not initialized or incompatible.")
                            response_text = "申し訳ありません、現在応答を生成できません。"

                        # self.performance_optimizer.log_memory_usage(f"After Gemini call for {character_name}")
                        # logger.info(f"Generated response for {character_name}: {response_text}")
                        # 会話履歴に記録（従来のマネージャーでも記録）
                        self.character_manager.record_conversation(character['name'], response_text)
                        
                        # アクティビティマネージャーにユーザーとの対話を記録
                        await self.activity_manager.on_user_interaction(str(message.author.id))
                        
                        # 絵文字をランダムに付ける
                        if random.random() < 0.5 and 'emoji' in character:
                            response_text += f" {random.choice(character['emoji'])}"
                            
                        # メッセージを送信
                        embed = discord.Embed(
                            description=response_text,
                            color=int(character['color'], 16)
                        )
                        embed.set_author(name=character['name'])
                        await message.channel.send(embed=embed)
                          # ボイスチャンネルに参加していれば音声も送信
                        if self.voice_client and self.voice_client.is_connected():
                            await self.generate_and_queue_response(None, response_text)
                except Exception as e:
                    logger.error(f"メッセージ処理中にエラーが発生: {e}")
                    await message.channel.send("すみません、応答の生成中にエラーが発生しました。")

    async def process_voice_input(self, user_id: str, text: str):
        """音声入力を処理（音声認識からの呼び出し用）"""
        try:
            if not self.gemini_client:
                logger.warning("音声入力を受信しましたが、Geminiクライアントが初期化されていません")
                return
            
            character = self.character
            
            # 強化されたGeminiクライアントを使用
            if hasattr(self.gemini_client, 'generate_response'):
                response_text = await self.gemini_client.generate_response(
                    user_message=text,
                    discord_user_id=user_id,
                    username="音声ユーザー",
                    display_name="音声ユーザー"
                )
            else:
                response_text = await self.gemini_client.generate_response(
                    character_info=character,
                    user_activity=None,
                    conversation_history=self.character_manager.get_conversation_history()
                )
            
            # 会話履歴に記録
            self.character_manager.record_conversation(character['name'], response_text)
            
            # 音声で応答
            if self.voice_client and self.voice_client.is_connected():
                await self.generate_and_queue_response(None, response_text)
            
            logger.info(f"音声入力に応答しました: {text[:50]}...")
            
        except Exception as e:
            logger.error(f"音声入力処理中にエラーが発生: {e}")

    async def process_audio_queue(self):
        """音声キューを処理するタスク"""
        if not self.voice_client or not self.voice_client.is_connected():
            return
            
        if not self.is_speaking and not self.audio_queue.empty():
            self.is_speaking = True
            audio_path = await self.audio_queue.get()
            
            try:
                # 音声ファイルの再生
                if os.path.exists(audio_path):
                    self.voice_client.play(discord.FFmpegPCMAudio(audio_path), 
                                    after=lambda e: asyncio.run_coroutine_threadsafe(
                                        self.on_audio_finished(audio_path, e), self.loop))
                    logger.info(f"Bot {self.bot_id} の音声再生開始: {audio_path}")
                else:
                    logger.error(f"音声ファイルが存在しません: {audio_path}")
                    self.is_speaking = False
            except Exception as e:
                logger.error(f"音声再生中にエラーが発生しました: {e}")
                self.is_speaking = False
    
    async def on_audio_finished(self, audio_path, error):
        """音声再生が完了したときのコールバック"""
        # 一時ファイルの削除
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
                logger.debug(f"一時ファイルを削除しました: {audio_path}")
        except Exception as e:
            logger.error(f"一時ファイルの削除中にエラーが発生しました: {e}")
        
        if error:
            logger.error(f"音声再生中にエラーが発生しました: {error}")
        
        # スピーキングフラグの解除
        self.is_speaking = False
    
    async def random_voice_chat(self):
        """ランダムなタイミングで話題を振るタスク"""
        if not self.voice_client or not self.voice_client.is_connected():
            return
            
        # 既に話している場合はスキップ
        if self.is_speaking:
            return
            
        now = datetime.now()
        cooldown = random.randint(10, 20)  # 10〜20秒のランダムなクールダウン
        
        # クールダウン期間が過ぎていない場合はスキップ
        if (now - self.random_talk_cooldown).total_seconds() < cooldown:
            return
          # 他のボットが話しているかチェック
        # any_speaking = any(bot.is_speaking for bot in bots if bot.activity_manager.bot_states[str(bot.bot_id)].is_active)
        # if any_speaking:
        #     return
        
        # ボットがアクティブで、応答すべきかを確認
        if not self.activity_manager.should_bot_respond(str(self.bot_id)):
            return
            
        # 話題を生成する確率（各ボットのActivityStateから取得）
        if str(self.bot_id) in self.activity_manager.bot_states:
            bot_state = self.activity_manager.bot_states[str(self.bot_id)]
            activity_rate = bot_state.get_adjusted_activity_rate()
        else:
            activity_rate = 0.1 # デフォルト値
            
        if random.random() < activity_rate:
            self.random_talk_cooldown = now
            if self.character:
                game_name = user_status["game_name"] if user_status["is_playing"] else None
                await self.generate_and_queue_response(game_name)
                # アクティビティマネージャーに自発的発言を記録
                await self.activity_manager.on_spontaneous_speech()
    
    async def random_text_chat(self):
        """ランダムなタイミングでテキストチャットに話題を振るタスク"""
        global user_status
        
        if TEXT_CHANNEL_ID == 0:
            return
            
        # 設定を読み込む
        config = load_config()
        random_text_chat_config = config.get("bot_activity", {}).get("random_text_chat", {})
        cooldown_range = random_text_chat_config.get("cooldown_seconds", [300, 900])
        activity_rate_multiplier = random_text_chat_config.get("activity_rate_multiplier", 0.5)
            
        now = datetime.now()
        cooldown = random.randint(cooldown_range[0], cooldown_range[1])
          # クールダウン期間が過ぎていない場合はスキップ
        if (now - self.text_chat_cooldown).total_seconds() < cooldown:
            return
              # 話題を生成する確率（動的活動レート）
        if str(self.bot_id) in self.activity_manager.bot_states:
            bot_state = self.activity_manager.bot_states[str(self.bot_id)]
            activity_rate = bot_state.get_adjusted_activity_rate()
        else:
            activity_rate = 0.1 # デフォルト値
            
        text_activity_rate = activity_rate * activity_rate_multiplier
        
        logger.debug(f"ランダムテキストチャット (Bot {self.bot_id}): 活動レート={activity_rate:.2f}, テキスト活動レート={text_activity_rate:.2f}, クールダウン={cooldown}秒")
          # このボットが発言するかどうかを判定
        if not self.activity_manager.should_bot_respond(str(self.bot_id), {'type': 'random_text_chat'}):
            return
              # さらに、現在アクティブなボットの中から1体だけが発言するように制御
        active_bots = []
        for b_id, b_state in self.activity_manager.bot_states.items():
            if b_state.is_active and int(b_id) < len(bots):
                bot_instance = bots[int(b_id)]
                if hasattr(bot_instance, 'random_text_chat_task') and bot_instance.random_text_chat_task and bot_instance.random_text_chat_task.is_running():
                    active_bots.append(bot_instance)
        if not active_bots: # アクティブなボットがいない場合は何もしない
            return
            
        # 発言するボットを1体選ぶ (自分自身が含まれている場合のみ発言のチャンスがある)
        # この制御は、複数のボットが同時に `random_text_chat` を実行することを前提としている
        # より厳密な制御のためには、共有ロックやグローバルな発言許可フラグが必要になるが、ここでは簡易的な対応とする
        if self not in active_bots: # 自分がアクティブリストに含まれていない場合は発言しない
            return
            
        # 実際に発言するボットを決定 (アクティブなボットの中からランダムに1体選ぶ)
        # ただし、この処理は各ボットインスタンスで独立して行われるため、
        # 複数のボットが同時にこの条件を満たす可能性がある。
        # これを防ぐには、共有の状態管理（例：Redisやグローバル変数）が必要。
        # ここでは、確率的に1体が選ばれることを期待する。
        if random.random() > (1.0 / len(active_bots)): # ボット数が多いほど発言確率は下がる
            return

        logger.info(f"Bot {self.bot_id} がランダムテキストチャットの送信を試みます。")

        if random.random() < text_activity_rate:
            self.text_chat_cooldown = now
            if self.character and self.gemini_client:
                game_name = user_status["game_name"] if user_status["is_playing"] else None
                # Geminiで応答を生成
                if hasattr(self.gemini_client, 'generate_response'):
                    # 強化されたクライアントの場合
                    user_id = "system"
                    response_text = await self.gemini_client.generate_response(
                        user_message=f"ユーザーが{game_name}をプレイ中です。チャットで何か話題を振ってください。" if game_name else "チャットで何か話題を振ってください。",
                        discord_user_id=user_id,
                        username="システム",
                        display_name="システム"
                    )
                else:
                    # 従来のクライアントの場合
                    response_text = await self.gemini_client.generate_response(
                        character_info=self.character,
                        user_activity=game_name,
                        conversation_history=self.character_manager.get_conversation_history()
                    )
                
                # 会話履歴に記録
                self.character_manager.record_conversation(self.character['name'], response_text)
                
                # アクティビティマネージャーに自発的発言を記録
                await self.activity_manager.on_spontaneous_speech()
                
                # 絵文字をランダムに付ける
                if random.random() < 0.5 and 'emoji' in self.character:
                    response_text += f" {random.choice(self.character['emoji'])}"
                    
                # テキストチャンネルにメッセージを送信
                text_channel = self.get_channel(TEXT_CHANNEL_ID)
                if text_channel:                    embed = discord.Embed(
                        description=response_text,
                        color=int(self.character['color'], 16)
                    )
                    embed.set_author(name=self.character['name'])
                    await text_channel.send(embed=embed)

    async def generate_and_queue_response(self, game_name=None, text=None):
        """応答を生成して音声キューに追加する"""
        try:            
            # ボイスクライアントが接続されているかチェック
            if not self.voice_client or not self.voice_client.is_connected():
                logger.debug(f"Bot {self.bot_id}: ボイスクライアントが接続されていないため音声応答をスキップします")
                return
            
            # TTSクライアントが利用可能かチェック
            if not self.tts_client:
                logger.warning(f"Bot {self.bot_id}: TTSクライアントが利用できないため音声応答をスキップします")
                return
            
            # テキストが指定されていない場合はGeminiで生成
            if text is None:
                if not self.gemini_client:
                    logger.error("GeminiClientが初期化されていないため応答を生成できません")
                    # 簡単なフォールバック応答
                    text = "こんにちは！今はシンプルモードで動作しています。"
                else:
                    # Geminiで応答を生成
                    try:
                        if hasattr(self.gemini_client, 'generate_response'):
                            # 強化されたクライアントの場合
                            user_id = "system"
                            text = await self.gemini_client.generate_response(
                                user_message=f"ユーザーが{game_name}をプレイ中です。何か話しかけてください。" if game_name else "何か話しかけてください。",
                                discord_user_id=user_id,
                                username="システム",
                                display_name="システム"
                            )                        else:
                            # 従来のクライアントの場合
                            text = await self.gemini_client.generate_response(
                                character_info=self.character,
                                user_activity=game_name,
                                conversation_history=self.character_manager.get_conversation_history()
                            )
                    except Exception as e:
                        logger.error(f"Gemini応答生成中にエラー: {e}")
                        text = "すみません、今ちょっと考えがまとまりません。"
            
            # 会話履歴に記録
            self.character_manager.record_conversation(self.character['name'], text)
            logger.info(f"{self.character['name']} (Bot {self.bot_id}): {text}")
            
            # TTS音声合成を並列処理で高速化
            audio_path = await self.tts_client.text_to_speech_parallel(text, self.character['voicevox_speaker_id'])
            
            if audio_path:
                # 音声キューに追加
                await self.audio_queue.put(audio_path)
        except Exception as e:
            logger.error(f"応答生成中にエラーが発生しました: {e}")
      async def join_voice_channel(self, channel):
        """指定されたボイスチャンネルに接続する"""
        try:
            # 既に同じチャンネルに接続している場合は何もしない
            if self.voice_client and self.voice_client.is_connected():
                if self.voice_client.channel.id == channel.id:
                    logger.debug(f"Bot {self.bot_id} は既にボイスチャンネル '{channel.name}' に接続済みです")
                    return
                else:
                    # 異なるチャンネルに接続している場合は切断
                    logger.info(f"Bot {self.bot_id} を '{self.voice_client.channel.name}' から切断します")
                    await self.voice_client.disconnect()
                    self.voice_client = None
                    await asyncio.sleep(1)  # 切断後少し待機
            
            # 新しいチャンネルに接続
            logger.info(f"Bot {self.bot_id} がボイスチャンネル '{channel.name}' への接続を試行します")
            self.voice_client = await channel.connect(cls=discord.VoiceClient)
            logger.info(f"Bot {self.bot_id} がボイスチャンネル '{channel.name}' に接続しました")
            
        except discord.ClientException as e:
            if "Already connected to a voice channel" in str(e):
                logger.warning(f"Bot {self.bot_id} は既にボイスチャンネルに接続しています。強制切断を試行します。")
                try:
                    if self.voice_client:
                        await self.voice_client.disconnect()
                    self.voice_client = None
                    await asyncio.sleep(2)  # 切断後に待機
                    # 再接続を試行
                    self.voice_client = await channel.connect(cls=discord.VoiceClient)
                    logger.info(f"Bot {self.bot_id} が強制切断後にボイスチャンネル '{channel.name}' に接続しました")
                except Exception as reconnect_error:
                    logger.error(f"Bot {self.bot_id} の強制切断後の再接続に失敗: {reconnect_error}")
            else:
                logger.error(f"Bot {self.bot_id} のボイスチャンネル接続中にClientExceptionが発生: {e}")
        except Exception as e:
            logger.error(f"Bot {self.bot_id} のボイスチャンネル '{channel.name}' への接続中に予期しないエラーが発生: {e}")

    async def initialize_gemini_client(self):
        """現在のキャラクター用のGeminiクライアントを初期化"""
        if not self.character:
            logger.warning(f"Bot {self.bot_id}: キャラクターが設定されていません")
            return
        
        try:
            logger.info(f"Bot {self.bot_id}: {self.character['name']}用のGeminiクライアントを初期化中...")
            
            # プロジェクトルートパスを取得
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # 共通設定を取得
            common_config = self.config.get('gemini_settings', {})
            
            # CharacterManagerを使用してGeminiクライアントを作成
            self.gemini_client = self.character_manager.create_gemini_client(
                self.character, project_root, common_config
            )
            
            if self.gemini_client:
                client_type = "Enhanced" if hasattr(self.gemini_client, 'memory_db') else "Standard"
                logger.info(f"Bot {self.bot_id}: {client_type} Geminiクライアントが初期化されました")
            else:
                logger.warning(f"Bot {self.bot_id}: Geminiクライアントの初期化に失敗しました")
                
        except Exception as e:
            logger.error(f"Bot {self.bot_id}: Geminiクライアントの初期化エラー: {e}")
            self.gemini_client = None

    # async def start_management_loop(self):
    #     """Manages bot activities like random chat and status updates based on activity_manager."""
    #     # This loop's responsibilities are now delegated to BotActivityManager
    #     # Kept for reference or if direct bot-specific management is needed again.
    #     # try:
    #     #     while True:
    #     #         # logger.debug(f"Bot {self.character_name} management loop iteration.")
    #     #         # Check if bot is active before proceeding
    #     #         if not self.activity_manager.get_bot_state(self.character_id).is_active:
    #     #             # logger.info(f"Bot {self.character_name} is inactive. Skipping management tasks.")
    #     #             await asyncio.sleep(self.config['discord']['management_update_interval_seconds'])
    #     #             continue
                
    #     #         # Random Text Chat Management
    #     #         if self.config['features']['random_text_chat']['enabled'] and self.activity_manager.get_bot_state(self.character_id).random_chat_enabled:
    #     #             if self.random_text_chat_task is None or self.random_text_chat_task.done():
    #     #                 # logger.info(f"Random text chat task for {self.character_name} is not running or done. Restarting.")
    #     #                 self.random_text_chat_task = asyncio.create_task(self.random_text_chat_session())
    #     #         elif self.random_text_chat_task and not self.random_text_chat_task.done():
    #     #             # logger.info(f"Disabling random text chat for {self.character_name}. Cancelling task.")
    #     #             self.random_text_chat_task.cancel()
    #     #             try:
    #     #                 await self.random_text_chat_task
    #     #             except asyncio.CancelledError:
    #     #                 logger.info(f"Random text chat task for {self.character_name} cancelled successfully.")
    #     #             self.random_text_chat_task = None

    #     #         # Update Presence/Activity
    #     #         try:
    #     #             current_activity_name = self.activity_manager.get_activity_name(self.character_id)
    #     #             if current_activity_name and (self.activity is None or self.activity.name != current_activity_name):
    #     #                 new_activity = discord.Game(name=current_activity_name)
    #     #                 await self.change_presence(activity=new_activity)
    #     #                 logger.info(f"Bot {self.character_name} activity updated to: {current_activity_name}")
    #     #             elif not current_activity_name and self.activity is not None:
    #     #                 await self.change_presence(activity=None)
    #     #                 logger.info(f"Bot {self.character_name} activity cleared.")
    #     #         except Exception as e:
    #     #             logger.error(f"Error updating presence for {self.character_name}: {e}", exc_info=True)
                
    #     #         await asyncio.sleep(self.config['discord']['management_update_interval_seconds'])
    #     # except asyncio.CancelledError:
    #     #     logger.info(f"Management loop for {self.character_name} was cancelled.")
    #     # except Exception as e:
    #     #     logger.error(f"Critical error in management_loop for {self.character_name}: {e}", exc_info=True)
    #     # finally:
    #     #     logger.info(f"Management loop for {self.character_name} has ended.")

# タイマーとフラグ
user_status = {
    "is_playing": False,
    "game_name": None,
    "in_voice_channel": False,
    "left_voice_at": None,
    "needs_greeting": False,
    "online_status": False,
    "last_autonomous_join": None
}

# ボットのインスタンスを作成
bots = []

# トークン数に基づいてボットを作成（BOT_COUNTを上限とする）
max_bots = min(BOT_COUNT, len(BOT_TOKENS))
logger.info(f"作成するボットの数: {max_bots}")

for i in range(max_bots):
    if i < len(BOT_TOKENS) and BOT_TOKENS[i].strip():
        logger.info(f"Bot {i} を作成中...")
        bot = CharacterBot(i)
        bots.append(bot)
        logger.info(f"Bot {i} の作成完了")

if not bots and DISCORD_TOKEN:
    bot = CharacterBot(0)
    bots.append(bot)

# 音声認識関連
voice_recognition_active = False

@tasks.loop(seconds=5.0)
async def check_user_status(bot):
    """ユーザーの状態を監視するタスク（メインボット＝0番のみ実行）"""
    global user_status

    if TARGET_USER_ID == 0:
        logger.error("TARGET_USER_ID が設定されていません")
        return

    # ターゲットユーザーの取得
    user = bot.get_user(TARGET_USER_ID)
    if not user:
        logger.warning(f"ユーザー (ID: {TARGET_USER_ID}) が見つかりません")
        return

    # ユーザーのアクティビティ確認
    previous_game_name = user_status["game_name"]
    previous_online_status = user_status["online_status"]
    user_status["is_playing"] = False
    user_status["game_name"] = None
    user_status["online_status"] = False

    for guild in bot.guilds:
        member = guild.get_member(TARGET_USER_ID)
        if member:
            # オンラインステータスの確認
            user_status["online_status"] = str(member.status) != "offline"
            
            # ゲームステータスの確認
            for activity in member.activities:
                if activity.type == discord.ActivityType.playing:
                    user_status["is_playing"] = True
                    user_status["game_name"] = activity.name
                    logger.info(f"ユーザーは {activity.name} をプレイ中です")
                    break

            # ボイスチャンネル状態の確認
            voice_state = member.voice
            previous_in_voice = user_status["in_voice_channel"]
            user_status["in_voice_channel"] = voice_state is not None

            # ユーザーがボイスチャンネルに入った場合
            if not previous_in_voice and user_status["in_voice_channel"]:
                user_status["needs_greeting"] = True
                logger.info("ユーザーがボイスチャンネルに入りました")
                
                # 各ボットを5秒おきに順番にボイスチャンネルに接続
                for bot_instance in bots:
                    await asyncio.sleep(5)
                    await bot_instance.join_voice_channel(voice_state.channel)
                    
                    # 挨拶メッセージを用意
                    if bot_instance.character:
                        await bot_instance.generate_and_queue_response(user_status["game_name"])
                
            # ユーザーがボイスチャンネルから退出した場合
            elif previous_in_voice and not user_status["in_voice_channel"]:
                user_status["left_voice_at"] = datetime.now()
                logger.info("ユーザーがボイスチャンネルから退出しました")

    # ユーザーが退出してから3分経過したらボットも退出
    if user_status["left_voice_at"]:
        elapsed = datetime.now() - user_status["left_voice_at"]
        if elapsed > timedelta(minutes=3):
            for bot_instance in bots:
                if bot_instance.voice_client and bot_instance.voice_client.is_connected():
                    await bot_instance.voice_client.disconnect()
                    bot_instance.voice_client = None
                    
            user_status["left_voice_at"] = None
            logger.info("ユーザーの退出から3分経過したため、すべてのボットがボイスチャンネルから退出しました")

    # ゲームが変わった場合に各ボットにメッセージを用意
    if user_status["game_name"] != previous_game_name:
        if user_status["is_playing"]:
            logger.info(f"ゲーム変更を検出: {user_status['game_name']}")
            for bot_instance in bots:
                if bot_instance.voice_client and bot_instance.voice_client.is_connected():
                    # ランダムな待機時間を設定してボットごとに異なるタイミングで発言
                    await asyncio.sleep(random.uniform(1, 5))
                    await bot_instance.generate_and_queue_response(user_status["game_name"])
    
    # オンラインステータスが変わった場合
    if user_status["online_status"] != previous_online_status:
        if user_status["online_status"]:
            logger.info("ユーザーがオンラインになりました")
        else:
            logger.info("ユーザーがオフラインになりました")

def start_voice_recognition(bot):
    """音声認識を開始する（別スレッドで実行）"""
    global voice_recognition_active
    
    def voice_recognition_thread():
        global voice_recognition_active
        voice_recognition_active = True
        logger.info("音声認識スレッドを開始しました")
        
        try:
            # 音声認識の処理（実装は略）
            # 実際には音声認識ライブラリとDiscordの音声ストリームを連携させる必要がある
            while voice_recognition_active:
                # 音声認識処理がここに入る
                time.sleep(1)
        except Exception as e:
            logger.error(f"音声認識中にエラーが発生しました: {e}")
        finally:
            voice_recognition_active = False
    
    # 別スレッドで音声認識を実行
    threading.Thread(target=voice_recognition_thread, daemon=True).start()

async def autonomous_voice_join():
    """ユーザー不在でもボットが自律的にボイスチャンネルに参加するタスク"""
    # ユーザーがオンラインかつ、ボイスチャンネルにいない場合
    if (user_status["online_status"] and not user_status["in_voice_channel"] and
        VOICE_CHANNEL_ID != 0):
        
        now = datetime.now()
        # 前回の自律参加から30分以上経過しているか
        if (user_status["last_autonomous_join"] is None or
            (now - user_status["last_autonomous_join"]) > timedelta(minutes=30)):
            
            # ランダムなボットを選択
            if bots:
                bot = random.choice(bots)
                
                channel = bot.get_channel(VOICE_CHANNEL_ID)
                if channel:
                    await bot.join_voice_channel(channel)
                    user_status["last_autonomous_join"] = now
                    
                    # 参加メッセージを生成
                    if bot.character:
                        game_name = user_status["game_name"] if user_status["is_playing"] else None
                        await bot.generate_and_queue_response(game_name)
                        
                    # 30分後に自動退出するタイマーを設定
                    async def auto_leave():
                        await asyncio.sleep(30 * 60)  # 30分待機
                        # ユーザーが参加していない場合は退出
                        if not user_status["in_voice_channel"]:
                            if bot.voice_client and bot.voice_client.is_connected():
                                await bot.voice_client.disconnect()
                                bot.voice_client = None
                                logger.info(f"自律参加から30分経過したため、Bot {bot.bot_id} がボイスチャンネルから退出しました")
                    
                    asyncio.create_task(auto_leave())

def run_bots():
    """複数のBotを同時に起動する"""
    if not BOT_TOKENS:
        logger.error("BOT_TOKENS が設定されていません")
        return
        
    if TARGET_USER_ID == 0:
        logger.error("TARGET_USER_ID が設定されていません")
        return

    if not bots:
        logger.error("有効なボットが存在しません")
        return
    
    # 各Botを並列実行
    loop = asyncio.get_event_loop()
    
    # 各ボットの起動を確認するカウンター
    started_bots = 0
    
    # 各ボットを起動
    for i, bot in enumerate(bots):
        if i < len(BOT_TOKENS):
            token = BOT_TOKENS[i].strip()
            if token:
                # 各ボットを非同期で実行
                loop.create_task(bot.start(token))
                logger.info(f"Bot {i} の起動タスクを作成しました（トークン: {token[:5]}...）")
                started_bots += 1
    
    if started_bots == 0:
        logger.error("有効なトークンを持つボットがありません")
        return
    
    logger.info(f"{started_bots}個のボットを起動しました")
    
    # 自律的なボイスチャンネル参加タスクを登録
    async def autonomous_voice_join_task():
        while True:
            await asyncio.sleep(30)  # 初回は30秒待ってからチェック開始
            await autonomous_voice_join()
            await asyncio.sleep(300)  # その後は5分ごとにチェック
    
    loop.create_task(autonomous_voice_join_task())
      try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Botをシャットダウンしています...")
    except Exception as e:
        logger.error(f"実行中にエラーが発生しました: {e}")
    finally:
        # 適切なシャットダウン処理
        logger.info("クリーンアップを開始します...")
        
        # 実行中のタスクをキャンセル
        pending_tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending_tasks:
            task.cancel()
        
        # ボットを安全にクローズ
        async def cleanup_bots():
            for i, bot in enumerate(bots):
                try:
                    if hasattr(bot, '_ready') and bot._ready.is_set():
                        logger.info(f"Bot {i} をクローズしています...")
                        # ボイスクライアントの切断
                        if hasattr(bot, 'voice_client') and bot.voice_client:
                            try:
                                await bot.voice_client.disconnect()
                            except Exception as e:
                                logger.warning(f"Bot {i} のボイスクライアント切断エラー: {e}")
                        
                        # TTSクライアントのクローズ
                        if hasattr(bot, 'tts_client') and hasattr(bot.tts_client, 'close'):
                            try:
                                await bot.tts_client.close()
                            except Exception as e:
                                logger.warning(f"Bot {i} のTTSクライアントクローズエラー: {e}")
                        
                        # ボット自体のクローズ
                        await bot.close()
                        logger.info(f"Bot {i} のクローズが完了しました")
                except Exception as e:
                    logger.error(f"Bot {i} のクローズ中にエラー: {e}")
        
        # クリーンアップの実行
        try:
            loop.run_until_complete(asyncio.wait_for(cleanup_bots(), timeout=10.0))
        except asyncio.TimeoutError:
            logger.warning("クリーンアップがタイムアウトしました")
        except Exception as e:
            logger.error(f"クリーンアップ中にエラー: {e}")
        finally:
            # ループを安全にクローズ
            try:
                if not loop.is_closed():
                    loop.close()
                logger.info("シャットダウンが完了しました")
            except Exception as e:
                logger.error(f"ループクローズ中にエラー: {e}")

if __name__ == "__main__":
    # logs ディレクトリの作成
    os.makedirs("logs", exist_ok=True)
    
    # Botの起動
    run_bots()