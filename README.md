# 🤖 Enhanced Discord AI Chatbot

高度な機能を備えたDiscord AIチャットボットです。長期記憶、感情認識、音声対応、パフォーマンス最適化などの先進的な機能を搭載しています。

## 🌟 主要機能

### 🧠 長期記憶システム
- **永続的なユーザー学習**: 会話を通じてユーザーの好み、性格、情報を学習・記憶
- **文脈認識会話**: 過去の会話履歴を活用した自然な対話
- **事実抽出**: 会話から重要な情報を自動抽出して記憶
- **性格分析**: ユーザーの性格特性を分析・蓄積

### 🎭 動的活動管理
- **気分状態追跡**: ボットの気分（Happy, Excited, Tired, Melancholy等）をリアルタイム管理
- **エネルギーシステム**: 相互作用によるエネルギーレベルの変動
- **時間パターン認識**: 時刻に基づく活動パターンの自動調整
- **アクティビティモード**: Normal, Energetic, Calm, Sleepy, Social, Focusedモード

### 🔊 音声認識・合成
- **VoiceVOX連携**: 自然な日本語音声合成
- **音声認識**: Discord音声チャンネルでの音声入力認識
- **複数TTS対応**: 抽象化されたTTSエンジンシステム

### ⚡ パフォーマンス最適化
- **並列処理**: 高優先度タスクキューによる効率的な処理
- **リソース監視**: CPU・メモリ使用量の自動監視
- **自動スケーリング**: 負荷に応じた動的なパフォーマンス調整
- **非同期処理**: 応答性を保つ最適化されたタスク管理

### 🎮 Discord統合
- **マルチボット対応**: 複数ボットの同時運行
- **音声チャンネル自動参加**: ユーザーの行動に応じた自動対応
- **ステータス連動**: Discordステータスに基づく反応
- **キャラクター管理**: 複数のAIキャラクターの切り替え

## 🛠️ 技術仕様

### アーキテクチャ
- **データベース**: SQLAlchemy による永続化記憶システム
- **AI エンジン**: Google Gemini 2.0 Flash API
- **音声処理**: SpeechRecognition + VoiceVOX
- **フレームワーク**: discord.py + asyncio

### 新しいコンポーネント
1. **`MemoryDatabase`** - 長期記憶管理
2. **`EnhancedGeminiClient`** - 強化されたAI応答システム
3. **`BotActivityManager`** - 動的活動制御
4. **`PerformanceOptimizer`** - パフォーマンス最適化
5. **`VoiceRecognitionClient`** - 音声認識システム

## 📋 必要条件

- Python 3.8以上
- Discord Bot Token
- Google Gemini API Key
- VoiceVOX（ローカルまたはリモート）
- FFmpeg
- 推奨: 4GB+ RAM（長期記憶機能のため）

## 🚀 クイックスタート

### 1. インストール
```bash
git clone <repository-url>
cd discord-enhanced-chatbot
pip install -r requirements.txt
```

### 2. 設定ファイル
```bash
cp .env.example .env
# .envファイルを編集して必要な情報を入力
```

### 3. 初回セットアップ
```bash
# データベースの初期化
python src/memory_database.py

# 設定の確認
python examples/enhanced_features_demo.py
```

### 4. ボット起動
```bash
python src/discord_bot.py
```

## ⚙️ 設定ガイド

### 環境変数設定 (`.env`)
```env
# Discord設定
DISCORD_TOKEN=your_discord_bot_token
BOT_TOKENS=token1,token2,token3  # 複数ボット用
TARGET_USER_ID=your_user_id
VOICE_CHANNEL_ID=voice_channel_id
TEXT_CHANNEL_ID=text_channel_id

# Gemini AI設定
GEMINI_API_KEY=your_gemini_api_key

# VoiceVOX設定
VOICEVOX_URL=http://localhost:50021
USE_PRIVILEGED_INTENTS=true

# パフォーマンス設定
BOT_COUNT=3
```

### 設定ファイル (`config/config.json`)
```json
{
  "bot_activity": {
    "enable_mood_tracking": true,
    "enable_time_patterns": true,
    "activity_rate_range": [0.2, 0.8],
    "mood_and_energy": {
      "enable_mood_learning": true,
      "energy_decay_per_hour": 2.0
    }
  },
  "performance": {
    "max_concurrent_audio_generations": 2,
    "memory_cleanup_interval_minutes": 30
  }
}
```
# User ID to track
TARGET_USER_ID=your_discord_user_id_here
# Voice Channel ID
VOICE_CHANNEL_ID=your_voice_channel_id_here
# Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here
# VoiceVox Engine URL (デフォルトでは通常localhost:50021)
VOICEVOX_ENGINE_URL=http://localhost:50021
```

## キャラクター設定のカスタマイズ

`config/characters.json`ファイルを編集することで、キャラクターの設定をカスタマイズできます。

```json
{
  "characters": [
    {
      "name": "キャラクター名",
      "personality": "キャラクターの性格",
      "voicevox_speaker_id": 0, // VoiceVOXのスピーカーID
      "color": "FF69B4", // 色コード（埋め込みメッセージ用）
      "phrases": [
        "デフォルトのフレーズ1",
        "デフォルトのフレーズ2"
      ],
      "relationship": "ユーザーとの関係"
    }
  ]
}
```

## 使い方

1. VoiceVOXを起動

2. ボットを実行
   ```
   python main.py
   ```

3. Discordでゲームを開始し、ボイスチャンネルに参加すると、ボットが5秒後に参加して会話を始めます。

## 常時稼働させる方法

### Windowsの場合

1. バッチファイル(.bat)を作成
   ```batch
   @echo off
   cd /d "C:\path\to\AI_chatbot"
   python main.py
   pause
   ```

2. タスクスケジューラーで起動時に実行するように設定

### Linuxの場合

1. systemdのサービスを作成
   ```
   [Unit]
   Description=Discord VoiceVOX Chatbot
   After=network.target

   [Service]
   Type=simple
   User=<username>
   WorkingDirectory=/path/to/AI_chatbot
   ExecStart=/usr/bin/python3 /path/to/AI_chatbot/main.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

2. サービスを有効化して起動
   ```
   sudo systemctl enable discord-voicevox-chatbot.service
   sudo systemctl start discord-voicevox-chatbot.service
   ```

## トラブルシューティング

- ボットが反応しない場合は、`.env`ファイルの設定を確認してください。
- VoiceVOXが正常に動作しているか確認してください。
- ログファイル(`logs/bot.log`と`logs/main.log`)でエラーがないか確認してください。
- Discordボットに適切な権限が付与されているか確認してください。

## ライセンス

MITライセンス
