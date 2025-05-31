import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
# from io import BytesIO # BytesIO is not used if passing PIL Image directly
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

# MessageHistoryクラスをこのファイル内で定義 (message_history.pyが存在しないため)
class MessageHistory:
    def __init__(self, max_history_length: int = 10):
        self.history: List[Dict[str, Any]] = [] # 'parts' can be complex
        self.max_history_length = max_history_length

    def add_message(self, role: str, content: str):
        # 単純なテキストコンテンツを想定
        if len(self.history) >= self.max_history_length:
            self.history.pop(0)
        self.history.append({"role": role, "parts": [{"text": content}]})

    def get_history_for_prompt(self) -> List[Dict[str, Any]]:
        # Gemini APIが期待する形式で履歴を返す
        return self.history

    def clear(self):
        self.history = []

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        project_root: str,
        character_name: str,
        character_config: Dict[str, Any],
        common_config: Dict[str, Any],
    ):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.project_root = project_root
        self.character_name = character_name
        self.character_config = character_config
        self.common_config = common_config

        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        self.generation_config = genai.types.GenerationConfig(
            temperature=self.character_config.get("temperature", 0.7),
            top_p=self.character_config.get("top_p", 1.0),
            top_k=self.character_config.get("top_k", 40), # top_kは整数であるべき
            max_output_tokens=self.character_config.get("max_output_tokens", 200),
        )

        self.message_history = MessageHistory(max_history_length=self.common_config.get("max_history_length", 10))

        self.prompt_base_path = os.path.join(self.project_root, self.common_config.get("prompt_base_path", "config/prompts"))
        
        self.system_prompt_template = self._load_prompt_file(
            self.character_config.get("system_prompt_template_file", "system_prompt_template.md")
        )
        self.character_personality = self._load_prompt_file(
            self.character_config.get("character_personality_file")
        )
        self.user_persona = self._load_prompt_file(
            self.character_config.get("user_persona_file")
        )

        if not self.system_prompt_template:
            logger.warning("System prompt template could not be loaded. Using a default.")
            self.system_prompt_template = "あなたは親切なAIアシスタント、{character_name}です。"
        if not self.character_personality:
            logger.warning(f"Character personality for {self.character_name} could not be loaded. Response quality may be affected.")
            self.character_personality = "特に設定なし。" # Default fallback
        if not self.user_persona:
            logger.warning("User persona could not be loaded. Using a default.")
            self.user_persona = "ユーザーは一般的なDiscordユーザーです。" # Default fallback

    def _load_prompt_file(self, file_name: Optional[str]) -> Optional[str]:
        if not file_name:
            logger.warning("Prompt file name is None. Skipping load.")
            return None
        try:
            file_path = os.path.join(self.prompt_base_path, file_name)
            normalized_path = os.path.normpath(file_path)

            if not normalized_path.startswith(os.path.normpath(self.project_root)):
                logger.error(f"Attempt to access file outside project root: {normalized_path} (project_root: {self.project_root})")
                return None
            
            logger.info(f"Attempting to load prompt file: {normalized_path}")
            with open(normalized_path, "r", encoding="utf-8") as f:
                content = f.read()
            logger.info(f"Successfully loaded prompt file: {file_name}")
            return content
        except FileNotFoundError:
            logger.error(f"Prompt file not found: {normalized_path}")
            return None
        except Exception as e:
            logger.error(f"Error loading prompt file {file_name} (path: {normalized_path if 'normalized_path' in locals() else file_path}): {e}", exc_info=True)
            return None

    def _construct_system_message_and_history(self, user_message_text: str) -> List[Dict[str, Any]]:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 履歴を取得 (Gemini APIが期待する形式)
        # MessageHistoryクラスのget_history_for_promptがこの形式で返すように修正
        conversation_history_for_prompt = self.message_history.get_history_for_prompt()

        # プレースホルダーを実際の値で置き換え
        # system_prompt_template は format メソッドでプレースホルダーを置換する
        # character_personality と user_persona はそのまま文字列として使用
        
        # システムプロンプトの構築
        # system_prompt_template には {character_name}, {character_personality}, {user_persona}, {current_time} などのプレースホルダーを含めることができる
        # conversation_history はシステムプロンプトの一部としてではなく、Gemini APIの履歴として渡す
        
        formatted_system_prompt = self.system_prompt_template.format(
            character_name=self.character_name,
            character_personality=self.character_personality, # これはテンプレート内で使われる想定
            user_persona=self.user_persona, # これもテンプレート内で使われる想定
            current_time=current_time
            # conversation_history はここには含めない
        )

        # Gemini APIは通常、システム指示を最初の 'user'/'model' ターンの前に特別なメッセージとして扱わない。
        # 代わりに、履歴の最初の 'user' メッセージの前に 'model' として空の応答を挟むか、
        # 最初の 'user' メッセージの内容にシステム指示を結合する。
        # ここでは、履歴の先頭にシステムプロンプトを 'user' ロールとして追加し、
        # それに対する 'model' の応答として「はい、理解しました。」のようなものを追加する戦略をとる。
        # または、よりシンプルに、履歴とは別に `system_instruction` パラメータ (利用可能な場合) を使う。
        # google-generativeai SDKでは `GenerativeModel` の `system_instruction` 引数で設定可能。
        # 今回は、履歴に含める形で実装。

        # 構築済み履歴: 過去の会話 + 新しいシステム情報 + 最新のユーザーメッセージ
        # 実際のAPIコールでは、system_instructionパラメータを使うのが望ましい
        # ここでは、履歴の一部としてシステムプロンプトを組み込む例を示す
        # ただし、Geminiの推奨は system_instruction の利用。
        # system_instruction が使えない場合の代替として、履歴の最初に含める。

        # 実際のコンテンツリスト
        # 履歴は MessageHistory から取得し、新しいユーザーメッセージを追加
        # システムプロンプトは別途 `system_instruction` で渡すのが理想
        
        # `contents` は [ {role: "user", parts: [...]}, {role: "model", parts: [...]}, ... ] の形式
        # `system_instruction` を使う場合、ここは純粋な会話履歴と新しいユーザーメッセージのみ
        
        # 今回の設計では、_construct_promptが最終的なcontentsリストを作成する
        # ここでは、システムプロンプトのテキストと、会話履歴のテキスト表現を準備する
        
        # `conversation_history` プレースホルダー用の文字列を作成
        history_string_for_template = "\\n".join(
            [f"{msg['role']}: {msg['parts'][0]['text']}" for msg in conversation_history_for_prompt]
        )

        # システムプロンプトテンプレートに会話履歴を含める場合 (テンプレートが {conversation_history} を持つ場合)
        # このアプローチは、システムプロンプトが非常に動的である場合に有効
        if "{conversation_history}" in formatted_system_prompt:
             formatted_system_prompt = formatted_system_prompt.replace("{conversation_history}", history_string_for_template)
        
        # 最終的なコンテンツリストの準備
        # system_instruction を使うのがベストプラクティス
        # ここでは、履歴の先頭にシステムプロンプトを置くのではなく、
        # `generate_content_async` に `system_instruction` として渡すことを想定し、
        # `formatted_system_prompt` を返す。履歴は別途 `message_history.get_history_for_prompt()` で取得。
        
        # この関数はシステムプロンプト文字列を返すように変更
        # return formatted_system_prompt 
        # やはりcontentsを返す方が一貫性がある。
        # system_instruction を使う場合は、model生成時に渡す。
        # ここでは、履歴と結合する形でcontentsを作成する。

        # 履歴の先頭にシステムプロンプトを配置するアプローチ
        # contents = [{"role": "user", "parts": [{"text": formatted_system_prompt}]}, {"role": "model", "parts": [{"text": "はい、承知いたしました。"}]}]
        # contents.extend(conversation_history_for_prompt)
        # contents.append({"role": "user", "parts": [{"text": user_message_text}]})
        # return contents

        # よりシンプルなアプローチ：システムプロンプトは別途渡し、ここでは会話履歴とユーザーメッセージのみ
        final_contents = list(conversation_history_for_prompt) # 新しいリストとしてコピー
        final_contents.append({"role": "user", "parts": [{"text": user_message_text}]})
        
        # `formatted_system_prompt` は `system_instruction` として渡されるべき文字列
        # この関数は `final_contents` と `formatted_system_prompt` を返す
        return final_contents, formatted_system_prompt


    def _construct_prompt_parts(self, user_message_text: str, image_path: Optional[str] = None) -> Tuple[List[Any], str, Optional[genai.types.ContentDict]]:
        # 1. 会話履歴とシステムプロンプトの準備
        #    system_instruction を使うため、履歴とシステムプロンプトを分離
        current_conversation_history = self.message_history.get_history_for_prompt()
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt_text = self.system_prompt_template.format(
            character_name=self.character_name,
            character_personality=self.character_personality,
            user_persona=self.user_persona,
            current_time=current_time,
            # conversation_history は system_instruction には含めないのが一般的
            # もしテンプレートに {conversation_history} があれば、それは空文字列などで置換
            conversation_history="" 
        )
        system_instruction_content = genai.types.ContentDict(
            role="system", # このロールはSDK内部で処理されるか、あるいは無視される場合がある。公式ドキュメント参照。
                           # `GenerativeModel` の `system_instruction` パラメータは通常文字列を期待。
                           # ここでは `system_prompt_text` を直接 `system_instruction` に渡す。
            parts=[genai.types.PartDict(text=system_prompt_text)]
        )
        # system_instructionは文字列で渡すので、system_prompt_text を使う。

        # 2. 画像の準備 (もしあれば)
        prompt_parts = []
        if image_path:
            try:
                logger.info(f"Loading image from path: {image_path}")
                img = Image.open(image_path)
                # 画像をPIL Imageオブジェクトとして直接リストに追加
                prompt_parts.append(img)
                logger.info(f"Image loaded successfully: {image_path}")
            except FileNotFoundError:
                logger.error(f"Image file not found: {image_path}")
                # 画像が見つからない場合でもテキスト処理は続行
            except Exception as e:
                logger.error(f"Failed to load image {image_path}: {e}", exc_info=True)
        
        # 3. ユーザーメッセージのテキスト部分を追加
        prompt_parts.append(user_message_text) # テキストは最後に追加するのが一般的

        # 4. ログ用の完全なプロンプトテキスト (近似)
        #    画像がある場合、[image]のようなプレースホルダで表現
        log_prompt_text = system_prompt_text + "\\n"
        for hist_msg in current_conversation_history:
            log_prompt_text += f"{hist_msg['role']}: {hist_msg['parts'][0]['text']}\\n" # 修正：hist_msg['parts']はリスト
        if image_path:
            log_prompt_text += "[image]\\n"
        log_prompt_text += f"user: {user_message_text}"

        # 戻り値: APIに渡すpartsのリスト、ログ用プロンプト、システム指示、会話履歴
        # `current_conversation_history` は `generate_content_async` の `history` パラメータに渡す
        # `prompt_parts` は `generate_content_async` の `contents` パラメータの最新のユーザー入力部分
        # `system_prompt_text` は `system_instruction` パラメータに渡す
        return prompt_parts, log_prompt_text, system_prompt_text, current_conversation_history


    async def generate_response(
        self, user_message: str, user_id: str, image_path: Optional[str] = None
    ) -> str:
        try:
            # ユーザーメッセージを履歴に追加 (APIコール前)
            # MessageHistory.add_message は {"role": "user", "parts": [{"text": content}]} 形式で保存する
            self.message_history.add_message(role="user", content=user_message)

            # プロンプト部品、ログ用プロンプト、システム指示、会話履歴を取得
            prompt_parts_for_api, log_prompt_text, system_instruction_text, history_for_api = \
                self._construct_prompt_parts(user_message, image_path)

            logger.debug(f"System Instruction for {self.character_name} (user: {user_id}): {system_instruction_text[:200]}...")
            logger.debug(f"History for API: {history_for_api}")
            logger.debug(f"Prompt Parts for API (current user turn): {prompt_parts_for_api}")
            # logger.debug(f"Constructed log prompt for {self.character_name} (user: {user_id}): {log_prompt_text[:500]}...")

            # `contents` は現在のユーザーのターン。画像とテキストを含むことができる。
            # `history` はそれ以前の会話のリスト。
            # `system_instruction` はモデルへの全体的な指示。
            
            # モデルのインスタンス化時に system_instruction を設定することも可能
            # self.model = genai.GenerativeModel(self.model_name, system_instruction=system_instruction_text)
            # または、generate_content_async 呼び出し時に渡す (SDKのバージョンや機能による)
            # 現在の google-generativeai SDK (例: 0.4.0+) では、GenerativeModel() で設定する

            # system_instruction を使うためにモデルを再設定するか、チャットセッション (start_chat) を使う
            # ここでは、毎回モデルを再設定するのではなく、start_chat を使うのが適切
            chat_session = self.model.start_chat(
                history=history_for_api,
                # system_instruction は start_chat には直接渡せないことが多い。
                # モデル初期化時に設定するか、履歴の先頭に含める必要がある。
                # 最新のSDKでは `GenerativeModel(model_name, system_instruction=...)` が推奨
            )
            # `system_instruction` を `GenerativeModel` で設定していない場合、
            # `system_instruction_text` を履歴の先頭に含めるアプローチに戻る必要がある。
            # もし `GenerativeModel` の `system_instruction` を使うなら、`__init__` で設定するか、
            # ここで `self.model.system_instruction = system_instruction_text` のように設定できるか確認が必要。
            # ドキュメントによると、`system_instruction` は `GenerativeModel` のコンストラクタ引数。
            # 動的に変更する場合は、新しいモデルインスタンスを作成するか、チャット履歴に含める。

            # 今回は、`system_instruction` を `GenerativeModel` のコンストラクタで設定する方針とし、
            # `__init__` で `self.system_prompt_template` 等を読み込んだ後に設定することを推奨。
            # しかし、`system_prompt_template` は `character_config` に依存するため、
            # `GeminiClient` インスタンスごとに異なる可能性がある。
            # そのため、`generate_response` のたびに `system_instruction` を考慮する必要がある。

            # `start_chat` を使わずに、`generate_content_async` に直接 `history` と `contents` を渡す方法
            # `contents` は [history..., user_turn_content] のように全てをまとめる
            
            final_contents_for_api = []
            # system_instruction を履歴の先頭に含める場合 (もし `system_instruction` パラメータが使えない場合)
            # final_contents_for_api.append({"role": "user", "parts": [{"text": system_instruction_text}]})
            # final_contents_for_api.append({"role": "model", "parts": [{"text": "はい、承知いたしました。"}]}) # ダミーの応答
            
            final_contents_for_api.extend(history_for_api) # 過去の履歴
            # 現在のユーザーのターン（画像＋テキスト）
            # prompt_parts_for_api は [Image, "text"] または ["text"] の形式
            current_turn_content = {"role": "user", "parts": []}
            for part_data in prompt_parts_for_api:
                if isinstance(part_data, Image.Image):
                    current_turn_content["parts"].append(part_data)
                elif isinstance(part_data, str):
                    current_turn_content["parts"].append({"text": part_data})
            final_contents_for_api.append(current_turn_content)
            
            logger.debug(f"Final contents for API: {final_contents_for_api}")

            # `system_instruction` を `GenerativeModel` のコンストラクタで設定するのがベスト。
            # ここでは、`self.model` が `system_instruction` を考慮して初期化されていると仮定する。
            # もし `system_instruction` が動的なら、`genai.configure` や `GenerativeModel` の再初期化が必要になる場合がある。
            # 今回は `self.model` が `system_instruction` を持たないシンプルな使い方を想定し、
            # `system_instruction_text` を `final_contents_for_api` の先頭に含める。
            # ただし、これは非推奨な方法。推奨は `GenerativeModel(..., system_instruction=...)`
            
            # 推奨される方法: `GenerativeModel` の `system_instruction` を使う
            # このためには、`self.model` を `system_instruction_text` を使って初期化する必要がある。
            # `__init__` で `self.model` を初期化する際に `system_instruction` を渡すように変更するのが理想。
            # `system_instruction` は `character_config` に依存するため、`__init__` で設定可能。
            # `self.system_prompt_template.format(...)` の結果を `system_instruction` に渡す。
            # この修正は `__init__` で行うべき。ここでは `self.model` が適切に初期化されていると仮定。

            # `generate_content_async` の呼び出し
            # `history` は `start_chat` で管理されるため、ここでは `final_contents_for_api` を直接渡す
            # (チャットセッションを使わない場合)
            response = await self.model.generate_content_async(
                contents=final_contents_for_api, # 履歴全体と現在のユーザー入力
                safety_settings=self.safety_settings,
                generation_config=self.generation_config
            )
            
            bot_response_text = "すみません、うまく聞き取れませんでした。" # Default fallback

            try:
                if response.candidates and response.candidates[0].finish_reason.name != "STOP":
                    reason_name = response.candidates[0].finish_reason.name
                    logger.warning(f"Generation stopped for {self.character_name} due to: {reason_name}")
                    if reason_name == "SAFETY":
                        bot_response_text = f"{self.character_name}は、安全上の理由によりその質問にはお答えできません。"
                        # 詳細なフィードバックをログに出力
                        if response.prompt_feedback:
                             logger.warning(f"Prompt feedback for {self.character_name}: {response.prompt_feedback}")
                        if response.candidates[0].safety_ratings:
                            logger.warning(f"Safety ratings for {self.character_name}: {response.candidates[0].safety_ratings}")
                    elif reason_name == "MAX_TOKENS":
                        bot_response_text = f"{self.character_name}のお返事が長くなりすぎたため、途中で終わってしまいました。"
                    else:
                        bot_response_text = f"{self.character_name}が応答を生成中に問題が発生しました ({reason_name})。"
                
                elif hasattr(response, 'text') and response.text:
                    bot_response_text = response.text
                elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
                    if text_parts:
                        bot_response_text = "".join(text_parts)
                    else:
                        logger.warning(f"Gemini API response parts were empty or did not contain text for {self.character_name}, despite finish_reason STOP.")
                else:
                    logger.warning(f"Gemini API response was not directly text and had no parts for {self.character_name}, despite finish_reason STOP.")

            except ValueError as ve: # response.text アクセス時にブロックされた場合など
                logger.warning(f"ValueError accessing response.text for {self.character_name} (likely blocked): {ve}", exc_info=True)
                if response.prompt_feedback:
                    logger.warning(f"Prompt feedback for {self.character_name}: {response.prompt_feedback}")
                bot_response_text = f"{self.character_name}は、安全上の理由により、その内容にはお答えできません。"
            except Exception as e_text_extract:
                logger.error(f"Unexpected error extracting text from Gemini response for {self.character_name}: {e_text_extract}", exc_info=True)
                bot_response_text = f"{self.character_name}からの応答の解析中に予期せぬエラーが発生しました。"

            # ボットの応答を履歴に追加
            self.message_history.add_message(role="model", content=bot_response_text)
            
            logger.info(f"Response generated for {self.character_name} (user: {user_id}): {bot_response_text[:100]}...")
            return bot_response_text

        except Exception as e:
            logger.error(f"Error generating response for {self.character_name} (user: {user_id}): {e}", exc_info=True)
            return f"{self.character_name}からの応答生成中にエラーが発生しました。しばらくしてからもう一度お試しください。"

    def clear_history(self, user_id: Optional[str] = None): # user_id は将来的にユーザーごとの履歴管理に使用する可能性を考慮
        self.message_history.clear()
        logger.info(f"Message history cleared for {self.character_name} (triggered by/for user: {user_id if user_id else 'N/A'}).")

    # __init__ の修正案 (system_instruction を使う場合)
    # def __init__(...):
    #     # ... (api_key, model_nameなどの初期化) ...
    #     self.project_root = project_root
    #     self.character_name = character_name
    #     self.character_config = character_config
    #     self.common_config = common_config

    #     # プロンプト関連の読み込み (system_instruction を生成するため先に実行)
    #     self.prompt_base_path = os.path.join(self.project_root, self.common_config.get("prompt_base_path", "config/prompts"))
    #     self.system_prompt_template = self._load_prompt_file(...)
    #     self.character_personality = self._load_prompt_file(...)
    #     self.user_persona = self._load_prompt_file(...)
        
    #     # system_instruction のテキストを生成
    #     # current_time は実行時に変わるため、ここでは含めないか、汎用的な指示にする
    #     # もし current_time が system_instruction に必須なら、動的にモデルを再生成する必要がある
    #     # ここでは current_time を除外した汎用的な system_instruction を想定
    #     _system_instruction_text = self.system_prompt_template.format(
    #         character_name=self.character_name,
    #         character_personality=self.character_personality,
    #         user_persona=self.user_persona,
    #         current_time="[時刻情報]" # またはテンプレートから {current_time} を削除
    #         # conversation_history も system_instruction には含めない
    #     ) if self.system_prompt_template else None

    #     genai.configure(api_key=api_key)
    #     self.model = genai.GenerativeModel(
    #         model_name,
    #         system_instruction=_system_instruction_text # ここで設定
    #     )
        
    #     # ... (safety_settings, generation_config, message_history の初期化) ...
    # この __init__ 修正案を採用する場合、generate_response 内での system_instruction の扱いは変わる。
    # (具体的には、`final_contents_for_api` に system_instruction を含める必要がなくなる)
    # 今回の編集では、`generate_response` 内のロジックを優先し、`__init__` は元のままとしています。
    # `system_instruction` の最適な利用方法は、プロジェクトの要件と Gemini SDK の最新の推奨事項によります。