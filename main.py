#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Discord VoiceVOX チャットボット
ユーザーのステータスを監視し、ゲームプレイ中に複数キャラクターでボイスチャットを行うボット
"""

import os
import sys
import logging
import traceback

def main():
    """メイン実行関数"""
    try:
        # logsディレクトリの作成
        os.makedirs("logs", exist_ok=True)
        
        # ロギングの設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("logs/main.log", encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        logger = logging.getLogger(__name__)
        
        logger.info("Discord VoiceVOX チャットボットを起動します...")
        
        # Discord botの起動
        from src.discord_bot import run_bots
        run_bots()
        
    except ImportError as e:
        print(f"インポートエラー: {e}")
        print("必要なライブラリがインストールされていない可能性があります。")
        print("requirements.txtからパッケージをインストールしてください:")
        print("pip install -r requirements.txt")
        input("Enterキーを押して終了...")
        
    except Exception as e:
        print(f"予期しないエラーが発生しました: {e}")
        print("詳細なエラー情報:")
        traceback.print_exc()
        input("Enterキーを押して終了...")

if __name__ == "__main__":
    main()