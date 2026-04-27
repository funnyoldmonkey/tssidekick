import warnings
# Must be before ANY other imports to effectively suppress the warning
warnings.filterwarnings("ignore", category=FutureWarning)

import os
import time
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class GemmaClient:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("⚠️ WARNING: GOOGLE_API_KEY not found in .env")
        genai.configure(api_key=api_key)
        self.last_request_time = 0
        self.min_interval = 4.2  # Respecting 15 RPM
        self.lock = asyncio.Lock()

    async def _wait_for_rate_limit(self):
        async with self.lock:
            current_time = time.time()
            elapsed = current_time - self.last_request_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await asyncio.sleep(wait_time)
            self.last_request_time = time.time()

    async def query(self, model_name, system_prompt, user_content, history=None):
        await self._wait_for_rate_limit()
        
        full_model_name = model_name if model_name.startswith("models/") else f"models/{model_name}"
        
        try:
            model = genai.GenerativeModel(
                model_name=full_model_name,
                system_instruction=system_prompt
            )
            
            chat = model.start_chat(history=history or [])
            response = await asyncio.to_thread(chat.send_message, user_content)
            
            # Check if the response was blocked or empty
            if not response.candidates or not hasattr(response.candidates[0].content, 'parts') or not response.candidates[0].content.parts:
                print(f"⚠️ Gemma blocked the response or returned empty. Feedback: {getattr(response, 'prompt_feedback', 'None')}")
                return '{"thought": "The AI model blocked the response. This usually happens due to safety filters or context length issues.", "action": "answer_user", "payload": {"message": "I was unable to process this request due to safety filters or a context error."}}'

            return response.text
        except Exception as e:
            error_msg = f"Error querying Gemma ({model_name}): {str(e)}"
            print(f"❌ {error_msg}")
            # Return a valid JSON error so the parser doesn't crash
            return f'{{"thought": "Query error.", "action": "answer_user", "payload": {{"message": "API Error: {str(e)}"}} }}'

gemma_client = GemmaClient()
