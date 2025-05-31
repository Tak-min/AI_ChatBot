import random
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import math

try:
    import discord
except ImportError:
    discord = None

logger = logging.getLogger(__name__)

class ActivityMode(Enum):
    """アクティビティモード"""
    NORMAL = "normal"
    ENERGETIC = "energetic"
    CALM = "calm"
    SLEEPY = "sleepy"
    SOCIAL = "social"
    FOCUSED = "focused"

class MoodState(Enum):
    """気分状態"""
    HAPPY = "happy"
    NEUTRAL = "neutral"
    TIRED = "tired"
    EXCITED = "excited"
    MELANCHOLY = "melancholy"

class BotActivityManager:
    """ボットの起動率とオフライン制御を管理するクラス"""
    def __init__(self, config: Dict[str, Any], bot_id: int, memory_db=None):
        self.config = config
        self.bot_id = bot_id # bot_id を属性として保存
        self.current_mood = MoodState.NEUTRAL
        
        # メモリデータベース参照
        self.memory_db = memory_db
        
        # 設定値
        bot_config = config.get('bot_activity', {})
        self.activity_rate_range = bot_config.get('activity_rate_range', [0.1, 0.6])
        self.random_interval = bot_config.get('random_activity_interval_seconds', [300, 1800])  # 5-30分
        self.enable_offline_mode = bot_config.get('enable_offline_mode', True)
        self.enable_mood_tracking = bot_config.get('enable_mood_tracking', True)
        self.enable_time_patterns = bot_config.get('enable_time_patterns', True)
        
        # ボットローテーション設定
        rotation_config = bot_config.get('bot_rotation', {})
        self.enable_bot_rotation = rotation_config.get('enabled', True)
        self.rotation_interval = timedelta(minutes=rotation_config.get('rotation_interval_minutes', 60))
        self.min_online_bots = rotation_config.get('min_online_bots', 2)
        self.max_online_bots = rotation_config.get('max_online_bots', 3)
        self.last_rotation = datetime.now()
        
        # ボット状態管理
        self.bot_states = {}  # bot_id -> ActivityState
        self.last_rate_change = datetime.now()
        self.rate_change_interval = timedelta(minutes=random.randint(10, 30))
        self.last_daily_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
          # アクティビティパターン学習
        self.activity_patterns = {}  # user_id -> interaction patterns
        
        # パフォーマンス監視
        from .performance_optimizer import PerformanceMonitor
        self.performance_monitor = PerformanceMonitor()

    # discord_bot.py側で各ボットのActivityStateから直接取得するため、このメソッドは不要
    # async def get_current_activity_rate(self) -> float:
    #     """現在の活動率を取得する"""
    #     # ボットIDに対応するボット状態が登録されている場合はその活動率を返す
    #     if str(self.bot_id) in self.bot_states:
    #         state = self.bot_states[str(self.bot_id)]
    #         if self.enable_time_patterns:
    #             return state.get_adjusted_activity_rate()
    #         return state.activity_rate
    #     
    #     # 未登録の場合はデフォルト値から計算
    #     base_rate = random.uniform(self.activity_rate_range[0], self.activity_rate_range[1])
    #     
    #     # 時間帯による調整（朝と夜は低め、昼と夕方は高め）
    #     hour = datetime.now().hour
    #     if 0 <= hour < 7:
    #         # 深夜帯は低め
    #         time_factor = 0.3
    #     elif 7 <= hour < 12:
    #         # 朝は普通
    #         time_factor = 0.8
    #     elif 12 <= hour < 18:
    #         # 昼から夕方は高め
    #         time_factor = 1.2
    #     elif 18 <= hour < 22:
    #         # 夜は普通
    #         time_factor = 1.0
    #     else:
    #         # 深夜は低め
    #         time_factor = 0.5
    #     
    #     adjusted_rate = base_rate * time_factor
    #     
    #     # 0.0-1.0の範囲に制限
    #     return max(0.0, min(1.0, adjusted_rate))
        
    async def register_bot(self, bot_id: str, bot_instance, custom_config: dict = None):
        """ボットを登録"""
        initial_rate = random.uniform(self.activity_rate_range[0], self.activity_rate_range[1])
        
        state = ActivityState(
            bot_id=bot_id,
            bot_instance=bot_instance,
            activity_rate=initial_rate,
            is_active=True,
            last_activity=datetime.now()
        )
        
        # カスタム設定の適用
        if custom_config:
            if 'preferred_active_hours' in custom_config:
                state.preferred_active_hours = custom_config['preferred_active_hours']
            if 'sleep_schedule' in custom_config:
                state.sleep_schedule = custom_config['sleep_schedule']
            if 'activity_patterns' in custom_config:
                state.activity_patterns.update(custom_config['activity_patterns'])
        
        self.bot_states[bot_id] = state
        
        # データベースに記録
        if self.memory_db:
            self.memory_db.update_bot_state(bot_id, True, initial_rate)
        
        logger.info(f"Bot {bot_id} を登録しました（活動率: {initial_rate:.2f}）")

    async def start_management_loop(self):
        """管理ループを開始"""
        while True:
            try:
                await self._check_daily_reset()
                await self._update_activity_states()
                await self._update_activity_rates()
                await self._manage_offline_bots()
                await self._rotate_online_bots()
                await self._monitor_performance()
                await self._learn_activity_patterns()
                await asyncio.sleep(60)  # 1分ごとにチェック
            except Exception as e:
                logger.error(f"活動管理ループエラー: {e}")
                await asyncio.sleep(60)
    
    async def _check_daily_reset(self):
        """日次リセットのチェック"""
        now = datetime.now()
        if now.date() > self.last_daily_reset.date():
            for state in self.bot_states.values():
                state.daily_reset()
            self.last_daily_reset = now.replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info("日次リセットを実行しました")
    
    async def _update_activity_states(self):
        """アクティビティ状態の更新"""
        for bot_id, state in self.bot_states.items():
            if self.enable_mood_tracking:
                state.update_mood()
                state.update_activity_mode()
            
            # エネルギーの自然減衰
            time_since_activity = (datetime.now() - state.last_activity).total_seconds() / 3600
            if time_since_activity > 1:  # 1時間以上非活動
                energy_decay = min(time_since_activity * 2, 10)
                state.energy_level = max(0, state.energy_level - energy_decay)
    
    async def _update_activity_rates(self):
        """活動率をランダムに更新"""
        now = datetime.now()
        
        if (now - self.last_rate_change) > self.rate_change_interval:
            for bot_id, state in self.bot_states.items():
                # 基本活動率の更新
                base_rate = random.uniform(self.activity_rate_range[0], self.activity_rate_range[1])
                state.activity_rate = base_rate
                
                # パフォーマンスに基づく調整
                if self.performance_monitor.is_high_load():
                    state.activity_rate *= 0.7  # 負荷が高い場合は活動率を下げる
                
                # データベース更新
                if self.memory_db:
                    adjusted_rate = state.get_adjusted_activity_rate()
                    self.memory_db.update_bot_state(bot_id, state.is_active, adjusted_rate)
                
                logger.debug(f"Bot {bot_id} の基本活動率を更新: {base_rate:.2f}")
              # 次回変更時刻を設定
            self.last_rate_change = now
            self.rate_change_interval = timedelta(minutes=random.randint(10, 30))
    
    async def _learn_activity_patterns(self):
        """アクティビティパターンの学習"""
        if not self.memory_db:
            return
        
        try:
            # ユーザーの活動パターンを学習
            current_hour = datetime.now().hour
            for bot_id, state in self.bot_states.items():
                if state.conversation_count_today > 0:
                    # 活動パターンの記録
                    pattern_key = f"{bot_id}_{current_hour}"
                    if pattern_key not in self.activity_patterns:
                        self.activity_patterns[pattern_key] = 0
                    self.activity_patterns[pattern_key] += 1
                    
                    # 学習結果をボット状態に反映
                    self._apply_learned_patterns(bot_id, state)
        except Exception as e:
            logger.error(f"アクティビティパターン学習エラー: {e}")
    
    def _apply_learned_patterns(self, bot_id: str, state):
        """学習したパターンをボット状態に適用"""
        current_hour = datetime.now().hour
        
        # この時間帯の過去の活動レベルを確認
        pattern_key = f"{bot_id}_{current_hour}"
        if pattern_key in self.activity_patterns:
            activity_count = self.activity_patterns[pattern_key]
            
            # 活動レベルに基づいてソーシャルファクターを調整
            if activity_count > 10:  # 高活動時間帯
                state.social_factor = min(100, state.social_factor + 5)
            elif activity_count < 3:  # 低活動時間帯
                state.social_factor = max(0, state.social_factor - 2)
    
    async def _monitor_performance(self):
        """パフォーマンスを監視"""
        self.performance_monitor.update()
        
        # 高負荷時の緊急対応
        if self.performance_monitor.is_critical_load():
            await self._emergency_scale_down()
    
    async def _emergency_scale_down(self):
        """緊急時のスケールダウン"""
        logger.warning("緊急スケールダウンを実行します")
        
        # 活動中のボットの半分をオフラインに
        active_bots = [bid for bid, state in self.bot_states.items() if state.is_active]
        if len(active_bots) > 1:
            bots_to_offline = random.sample(active_bots, len(active_bots) // 2)
            
            for bot_id in bots_to_offline:
                state = self.bot_states[bot_id]
                # 緊急時は強制的にエネルギーを下げる
                state.energy_level = max(0, state.energy_level - 30)
                state.mood_state = MoodState.TIRED
                await self._set_bot_offline(bot_id, state)
    
    async def _manage_offline_bots(self):
        """オフラインボットの管理"""
        if not self.enable_offline_mode:
            return
            
        for bot_id, state in self.bot_states.items():
            # 調整された活動率を使用
            adjusted_rate = state.get_adjusted_activity_rate() if self.enable_time_patterns else state.activity_rate
            
            # ローテーション機能が無効の場合のみこの従来のランダムなオフライン判定を使用
            if not self.enable_bot_rotation:
                # 活動率に基づいてオフライン判定
                if random.random() > adjusted_rate:
                    if state.is_active:
                        await self._set_bot_offline(bot_id, state)
                else:
                    if not state.is_active:
                        await self._set_bot_online(bot_id, state)
    
    async def _rotate_online_bots(self):
        """ボットのオンライン状態をローテーションさせる"""
        if not self.enable_bot_rotation or not self.enable_offline_mode:
            return
            
        now = datetime.now()
        if (now - self.last_rotation) < self.rotation_interval:
            return
            
        self.last_rotation = now
        logger.info(f"ボットローテーションを実行します（間隔: {self.rotation_interval.total_seconds() / 60}分）")
        
        try:
            # 現在のオンライン/オフラインボット数を確認
            active_bots = [bid for bid, state in self.bot_states.items() if state.is_active]
            inactive_bots = [bid for bid, state in self.bot_states.items() if not state.is_active]
            
            # オンラインボットが多すぎる場合は減らす
            if len(active_bots) > self.max_online_bots:
                # オフラインにするボット数
                num_to_offline = len(active_bots) - self.max_online_bots
                # ランダムに選択
                bots_to_offline = random.sample(active_bots, num_to_offline)
                
                for bot_id in bots_to_offline:
                    state = self.bot_states[bot_id]
                    await self._set_bot_offline(bot_id, state)
                    
            # オンラインボットが少なすぎる場合は増やす
            elif len(active_bots) < self.min_online_bots and inactive_bots:
                # オンラインにするボット数
                num_to_online = min(len(inactive_bots), self.min_online_bots - len(active_bots))
                # ランダムに選択
                bots_to_online = random.sample(inactive_bots, num_to_online)
                
                for bot_id in bots_to_online:
                    state = self.bot_states[bot_id]
                    await self._set_bot_online(bot_id, state)
            
            # ローテーションするケース（全てのボットを入れ替えない）
            elif inactive_bots:
                # 1-2体をランダムに入れ替え
                num_to_rotate = min(len(active_bots), len(inactive_bots), random.randint(1, 2))
                
                # 入れ替えるボットをランダム選択
                active_to_offline = random.sample(active_bots, num_to_rotate)
                inactive_to_online = random.sample(inactive_bots, num_to_rotate)
                
                # オフラインに変更
                for bot_id in active_to_offline:
                    state = self.bot_states[bot_id]
                    await self._set_bot_offline(bot_id, state)
                
                # オンラインに変更（すぐに変更するとミスる可能性があるので少し待つ）
                await asyncio.sleep(5)
                for bot_id in inactive_to_online:
                    state = self.bot_states[bot_id]
                    await self._set_bot_online(bot_id, state)
                    
                logger.info(f"ボットローテーション完了: {num_to_rotate}体のボットを入れ替えました")
                
        except Exception as e:
            logger.error(f"ボットローテーション中にエラーが発生: {e}")
    
    async def _set_bot_offline(self, bot_id: str, state):
        """ボットをオフラインに設定"""
        try:
            state.is_active = False
            state.offline_since = datetime.now()
            
            # Discordステータスを非表示に変更
            if discord and hasattr(state.bot_instance, 'change_presence'):
                await state.bot_instance.change_presence(status=discord.Status.invisible)
            
            # ボットのタスク停止（メソッドが存在する場合）
            if hasattr(state.bot_instance, 'disable_tasks'):
                await state.bot_instance.disable_tasks()
                logger.info(f"Bot {bot_id} のタスクを停止しました")
            
            # ボットの音声チャンネル離脱
            if hasattr(state.bot_instance, 'voice_client') and state.bot_instance.voice_client:
                if state.bot_instance.voice_client.is_connected():
                    await state.bot_instance.voice_client.disconnect()
                    logger.info(f"Bot {bot_id} をボイスチャンネルから離脱させました")
            
            # データベース更新
            if self.memory_db:
                self.memory_db.update_bot_state(bot_id, False, state.activity_rate)
            
            logger.info(f"Bot {bot_id} をオフラインに設定しました（モード: {state.activity_mode.value}, 気分: {state.mood_state.value}）")
            
        except Exception as e:
            logger.error(f"Bot {bot_id} のオフライン設定エラー: {e}")
    
    async def _set_bot_online(self, bot_id: str, state):
        """ボットをオンラインに設定"""
        try:
            state.is_active = True
            state.offline_since = None
            state.last_activity = datetime.now()
            
            # Discordステータスをオンラインに変更
            if discord and hasattr(state.bot_instance, 'change_presence'):
                await state.bot_instance.change_presence(status=discord.Status.online)
            
            # ボットのタスク再開（メソッドが存在する場合）
            if hasattr(state.bot_instance, 'enable_tasks'):
                await state.bot_instance.enable_tasks()
                logger.info(f"Bot {bot_id} のタスクを再開しました")
            
            # データベース更新
            if self.memory_db:
                self.memory_db.update_bot_state(bot_id, True, state.activity_rate)
            
            logger.info(f"Bot {bot_id} をオンラインに設定しました（モード: {state.activity_mode.value}, エネルギー: {state.energy_level:.1f}）")
            
        except Exception as e:
            logger.error(f"Bot {bot_id} のオンライン設定エラー: {e}")
    
    def should_bot_respond(self, bot_id: str, interaction_context: dict = None) -> bool:
        """ボットが応答すべきかを判定"""
        if bot_id not in self.bot_states:
            logger.warning(f"Bot {bot_id} is not registered in bot_states.")
            return False
            
        state = self.bot_states[bot_id]
        
        # オフラインの場合は応答しない
        if not state.is_active:
            return False
        
        # 調整された活動率を使用
        effective_rate = state.get_adjusted_activity_rate()
        
        # コンテキストに基づく追加調整
        if interaction_context:
            interaction_type = interaction_context.get('type', 'unknown')
            
            # ランダムテキストチャットの場合、他のボットが最近発言したかなどを考慮
            if interaction_type == 'random_text_chat':
                # TODO: 他のボットの最終発言時刻などを考慮して、連続投稿を避ける
                # 例: last_text_chat_time_by_any_bot を記録・参照する
                pass # 現状は追加の調整なし
                
            # 直接メンションの場合は応答率上昇
            if interaction_context.get('is_mention', False):
                effective_rate *= 1.5
            
            # 連続会話の場合の調整
            if interaction_context.get('is_continuation', False):
                if state.activity_mode == ActivityMode.SOCIAL:
                    effective_rate *= 1.2
                elif state.activity_mode == ActivityMode.SLEEPY:
                    effective_rate *= 0.7
            
            # 感情的なメッセージへの反応調整
            message_sentiment = interaction_context.get('sentiment', 'neutral')
            if message_sentiment == 'positive' and state.mood_state in [MoodState.HAPPY, MoodState.EXCITED]:
                effective_rate *= 1.3
            elif message_sentiment == 'negative' and state.mood_state == MoodState.MELANCHOLY:
                effective_rate *= 1.1
        
        # 最終的な判定
        should_respond = random.random() < min(1.0, effective_rate)
        if should_respond:
            logger.info(f"Bot {bot_id} will respond. Effective rate: {effective_rate:.2f}")
        else:
            logger.debug(f"Bot {bot_id} will not respond. Effective rate: {effective_rate:.2f}")
        return should_respond
    
    def update_bot_activity(self, bot_id: str, interaction_type: str = 'neutral', context: dict = None):
        """ボットの活動時刻と状態を更新"""
        if bot_id in self.bot_states:
            state = self.bot_states[bot_id]
            state.last_activity = datetime.now()
            state.total_messages += 1
            state.conversation_count_today += 1
            
            # 気分とエネルギーの更新
            if self.enable_mood_tracking:
                state.update_mood(interaction_type)
            
            # ソーシャルファクターの更新
            if context and context.get('user_count', 1) > 2:  # グループ会話
                state.social_factor = min(100, state.social_factor + 2)
            
            # エネルギーの回復（活動による）
            if interaction_type == 'positive':
                state.energy_level = min(100, state.energy_level + random.uniform(1, 3))
    
    def get_bot_status(self, bot_id: str) -> dict:
        """ボットの詳細ステータスを取得"""
        if bot_id not in self.bot_states:
            return {}
        
        state = self.bot_states[bot_id]
        return {
            'bot_id': bot_id,
            'is_active': state.is_active,
            'activity_rate': state.activity_rate,
            'adjusted_activity_rate': state.get_adjusted_activity_rate(),
            'activity_mode': state.activity_mode.value,
            'mood_state': state.mood_state.value,
            'energy_level': state.energy_level,
            'social_factor': state.social_factor,
            'total_messages': state.total_messages,
            'conversation_count_today': state.conversation_count_today,
            'positive_interactions': state.positive_interactions,
            'negative_interactions': state.negative_interactions,
            'last_activity': state.last_activity.isoformat(),
            'time_factor': state.get_current_time_factor(),
            'mood_factor': state.get_mood_factor(),
            'energy_factor': state.get_energy_factor()
        }
    
    def force_mood_change(self, bot_id: str, new_mood: MoodState, energy_change: float = 0):
        """強制的に気分を変更（デバッグ・テスト用）"""
        if bot_id in self.bot_states:
            state = self.bot_states[bot_id]
            state.mood_state = new_mood
            state.energy_level = max(0, min(100, state.energy_level + energy_change))
            state.last_mood_change = datetime.now()
            logger.info(f"Bot {bot_id} の気分を {new_mood.value} に変更しました（エネルギー: {state.energy_level:.1f}）")

    async def on_user_interaction(self, user_id: str, interaction_type: str = 'positive'):
        """ユーザーとの対話を記録"""
        if str(self.bot_id) in self.bot_states:
            state = self.bot_states[str(self.bot_id)]
            state.last_activity = datetime.now()
            state.total_messages += 1
            state.conversation_count_today += 1
            
            # 気分とエネルギーの更新
            if self.enable_mood_tracking:
                state.update_mood(interaction_type)
            
            # エネルギーの回復（ユーザーとの対話）
            state.energy_level = min(100, state.energy_level + random.uniform(3, 8))
            
            # データベース記録
            if self.memory_db and hasattr(self.memory_db, 'record_interaction'):
                await self.memory_db.record_interaction(user_id, str(self.bot_id), interaction_type)
            
            return True
        return False
    
    async def on_spontaneous_speech(self):
        """自発的発言の記録"""
        if str(self.bot_id) in self.bot_states:
            state = self.bot_states[str(self.bot_id)]
            state.last_activity = datetime.now()
            state.total_messages += 1
            
            # エネルギー消費（自発的発言）
            state.energy_level = max(0, state.energy_level - random.uniform(1, 3))
            
            return True
        return False

class ActivityState:
    """ボットの活動状態を表すクラス"""
    
    def __init__(self, bot_id: str, bot_instance, activity_rate: float, 
                 is_active: bool = True, last_activity: datetime = None):
        self.bot_id = bot_id
        self.bot_instance = bot_instance
        self.activity_rate = activity_rate
        self.is_active = is_active
        self.last_activity = last_activity or datetime.now()
        self.offline_since = None
        self.total_messages = 0
        self.errors_count = 0
        
        # Enhanced features
        self.activity_mode = ActivityMode.NORMAL
        self.mood_state = MoodState.NEUTRAL
        self.energy_level = 50.0  # 0-100
        self.social_factor = 50.0  # 0-100
        self.last_mood_change = datetime.now()
        self.conversation_count_today = 0
        self.positive_interactions = 0
        self.negative_interactions = 0
        
        # Time-based patterns
        self.preferred_active_hours = list(range(9, 22))  # 9AM to 10PM
        self.sleep_schedule = {'bedtime': 23, 'wakeup': 7}
        self.activity_patterns = {
            'morning': 0.8,
            'afternoon': 1.0,
            'evening': 0.9,
            'night': 0.3
        }
    
    def get_current_time_factor(self) -> float:
        """現在時刻に基づく活動係数を取得"""
        current_hour = datetime.now().hour
        
        if 6 <= current_hour < 12:  # Morning
            return self.activity_patterns['morning']
        elif 12 <= current_hour < 18:  # Afternoon
            return self.activity_patterns['afternoon']
        elif 18 <= current_hour < 22:  # Evening
            return self.activity_patterns['evening']
        else:  # Night
            return self.activity_patterns['night']
    
    def get_mood_factor(self) -> float:
        """気分に基づく活動係数を取得"""
        mood_multipliers = {
            MoodState.HAPPY: 1.2,
            MoodState.EXCITED: 1.4,
            MoodState.NEUTRAL: 1.0,
            MoodState.TIRED: 0.6,
            MoodState.MELANCHOLY: 0.8
        }
        return mood_multipliers.get(self.mood_state, 1.0)
    
    def get_energy_factor(self) -> float:
        """エネルギーレベルに基づく活動係数を取得"""
        return (self.energy_level / 100.0) * 1.5 + 0.2
    
    def update_mood(self, interaction_type: str = 'neutral'):
        """相互作用に基づいて気分を更新"""
        if interaction_type == 'positive':
            self.positive_interactions += 1
            self.energy_level = min(100, self.energy_level + random.uniform(2, 5))
            
            # ポジティブな相互作用で気分向上
            if self.mood_state in [MoodState.TIRED, MoodState.MELANCHOLY]:
                if random.random() < 0.3:
                    self.mood_state = MoodState.NEUTRAL
            elif self.mood_state == MoodState.NEUTRAL:
                if random.random() < 0.4:
                    self.mood_state = MoodState.HAPPY
            elif self.mood_state == MoodState.HAPPY:
                if random.random() < 0.2:
                    self.mood_state = MoodState.EXCITED
                    
        elif interaction_type == 'negative':
            self.negative_interactions += 1
            self.energy_level = max(0, self.energy_level - random.uniform(3, 7))
            
            # ネガティブな相互作用で気分低下
            if self.mood_state in [MoodState.HAPPY, MoodState.EXCITED]:
                if random.random() < 0.4:
                    self.mood_state = MoodState.NEUTRAL
            elif self.mood_state == MoodState.NEUTRAL:
                if random.random() < 0.3:
                    self.mood_state = random.choice([MoodState.TIRED, MoodState.MELANCHOLY])
        
        # 時間経過による自然な気分変化
        time_since_last_change = (datetime.now() - self.last_mood_change).total_seconds() / 3600
        if time_since_last_change > 2:  # 2時間以上経過
            if random.random() < 0.1:  # 10%の確率で気分変化
                self._natural_mood_change()
                self.last_mood_change = datetime.now()
    
    def _natural_mood_change(self):
        """自然な気分変化"""
        # エネルギーレベルと時刻に基づく気分変化
        current_hour = datetime.now().hour
        
        if current_hour in range(22, 24) or current_hour in range(0, 6):
            # 夜間は疲れやすい
            if random.random() < 0.6:
                self.mood_state = MoodState.TIRED
                self.energy_level = max(0, self.energy_level - 10)
        else:
            # 日中はよりアクティブ
            if self.energy_level > 70:
                mood_options = [MoodState.HAPPY, MoodState.EXCITED]
            elif self.energy_level < 30:
                mood_options = [MoodState.TIRED, MoodState.MELANCHOLY]
            else:
                mood_options = [MoodState.NEUTRAL, MoodState.HAPPY]
            
            self.mood_state = random.choice(mood_options)
    
    def update_activity_mode(self):
        """現在の状態に基づいてアクティビティモードを更新"""
        current_hour = datetime.now().hour
        
        # 時刻ベースの基本モード決定
        if current_hour in range(22, 24) or current_hour in range(0, 7):
            base_mode = ActivityMode.SLEEPY
        elif current_hour in range(7, 12):
            base_mode = ActivityMode.NORMAL
        elif current_hour in range(12, 18):
            base_mode = ActivityMode.ENERGETIC
        else:
            base_mode = ActivityMode.CALM
        
        # 気分とエネルギーレベルによる調整
        if self.mood_state == MoodState.EXCITED and self.energy_level > 80:
            self.activity_mode = ActivityMode.SOCIAL
        elif self.mood_state == MoodState.TIRED or self.energy_level < 20:
            self.activity_mode = ActivityMode.SLEEPY
        elif self.social_factor > 75:
            self.activity_mode = ActivityMode.SOCIAL
        elif self.conversation_count_today > 20:
            self.activity_mode = ActivityMode.FOCUSED
        else:
            self.activity_mode = base_mode
    
    def get_adjusted_activity_rate(self) -> float:
        """調整された活動率を取得"""
        base_rate = self.activity_rate
        time_factor = self.get_current_time_factor()
        mood_factor = self.get_mood_factor()
        energy_factor = self.get_energy_factor()
        
        # アクティビティモードによる調整
        mode_multipliers = {
            ActivityMode.NORMAL: 1.0,
            ActivityMode.ENERGETIC: 1.3,
            ActivityMode.CALM: 0.8,
            ActivityMode.SLEEPY: 0.4,
            ActivityMode.SOCIAL: 1.5,
            ActivityMode.FOCUSED: 0.9
        }
        
        mode_factor = mode_multipliers.get(self.activity_mode, 1.0)
        
        # 最終的な活動率計算
        adjusted_rate = base_rate * time_factor * mood_factor * energy_factor * mode_factor
        
        # 0.0-1.0の範囲に制限
        return max(0.0, min(1.0, adjusted_rate))
    
    def daily_reset(self):
        """日次リセット処理"""
        self.conversation_count_today = 0
        self.positive_interactions = 0
        self.negative_interactions = 0
        
        # エネルギーの自然回復
        if self.energy_level < 50:
            self.energy_level = min(100, self.energy_level + random.uniform(20, 30))
        
        # 気分のリセット傾向
        if random.random() < 0.3:
            self.mood_state = MoodState.NEUTRAL

class PerformanceMonitor:
    """パフォーマンス監視クラス"""
    
    def __init__(self):
        self.cpu_usage = 0.0
        self.memory_usage = 0.0
        self.last_update = datetime.now()
        self.high_load_threshold = 80.0
        self.critical_load_threshold = 95.0
    
    def update(self):
        """パフォーマンス情報を更新"""
        try:
            import psutil
            
            self.cpu_usage = psutil.cpu_percent(interval=1)
            self.memory_usage = psutil.virtual_memory().percent
            self.last_update = datetime.now()
            
        except ImportError:
            # psutilが利用できない場合は簡易監視
            self.cpu_usage = random.uniform(10, 50)  # ダミー値
            self.memory_usage = random.uniform(20, 60)
        except Exception as e:
            logger.error(f"パフォーマンス監視エラー: {e}")
    
    def is_high_load(self) -> bool:
        """高負荷状態かチェック"""
        return (self.cpu_usage > self.high_load_threshold or 
                self.memory_usage > self.high_load_threshold)
    
    def is_critical_load(self) -> bool:
        """クリティカル負荷状態かチェック"""
        return (self.cpu_usage > self.critical_load_threshold or 
                self.memory_usage > self.critical_load_threshold)
    
    def get_stats(self) -> dict:
        """統計情報を取得"""
        return {
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'last_update': self.last_update.isoformat(),
            'is_high_load': self.is_high_load(),
            'is_critical_load': self.is_critical_load()
        }

class ResourceManager:
    """リソース管理クラス"""
    
    def __init__(self, config: dict):
        self.config = config
        performance_config = config.get('performance', {})
        
        self.max_concurrent_audio = performance_config.get('max_concurrent_audio_generations', 2)
        self.audio_queue_size = performance_config.get('audio_queue_size', 10)
        self.cleanup_interval = performance_config.get('memory_cleanup_interval_minutes', 30)
        
        self.audio_semaphore = asyncio.Semaphore(self.max_concurrent_audio)
        self.last_cleanup = datetime.now()
    
    async def acquire_audio_slot(self):
        """音声生成スロットを取得"""
        await self.audio_semaphore.acquire()
    
    def release_audio_slot(self):
        """音声生成スロットを解放"""
        self.audio_semaphore.release()
    
    async def cleanup_if_needed(self):
        """必要に応じてメモリクリーンアップ"""
        now = datetime.now()
        if (now - self.last_cleanup).total_seconds() > (self.cleanup_interval * 60):
            await self._perform_cleanup()
            self.last_cleanup = now
    
    async def _perform_cleanup(self):
        """実際のクリーンアップ処理"""
        try:
            import gc
            gc.collect()
            logger.info("メモリクリーンアップを実行しました")
        except Exception as e:
            logger.error(f"クリーンアップエラー: {e}")
