import os
import discord
from supabase import create_client, Client
from google import genai
from google.genai import types

# 1. جلب مفاتيح الربط من المتغيرات (Environment Variables)
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# 2. تجهيز الاتصال بقاعدة بيانات Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 3. تجهيز الاتصال بـ Google Gemini
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 4. إعدادات بوت ديسكورد
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# تعليمات النظام (الشخصية اللي حيتقمصها البوت)
SYSTEM_INSTRUCTION = """أنت مساعد دراسي ذكي ومفيد لأحمد، طالب في الصف التاسع في طرابلس، ليبيا.
تساعده في فهم الدروس، حل التمارين، وتنظيم وقته للدراسة. 
لهجتك ليبية محببة وواضحة، وتشجعه دائماً على التفوق وتجاوز الصعوبات."""

@client.event
async def on_ready():
    print(f'✅ البوت {client.user} متصل وجاهز للعمل!')

@client.event
async def on_message(message):
    # عشان البوت ما يردش على نفسه
    if message.author == client.user:
        return
    
    # البوت يرد لو حد دارله منشن (Mention) أو في رسائل الخاص (DM)
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        # تنظيف الرسالة من اسم البوت
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        if not user_msg:
            return

        try:
            # 1. حفظ رسالة المستخدم في Supabase (جدول chat_history)
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "user",
                "content": user_msg
            }).execute()

            # 2. جلب آخر 10 رسائل من الذاكرة باش البوت يتذكر سياق الكلام
            response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()
            history_data = reversed(response.data) # ترتيبها من الأقدم للأحدث
            
            # 3. تجهيز الذاكرة لـ Gemini
            contents = []
            for row in history_data:
                contents.append(
                    types.Content(
                        role=row["role"], 
                        parts=[types.Part.from_text(text=row["content"])]
                    )
                )

            # 4. إرسال المحادثة لـ Gemini 3.6 Flash وتلقي الرد
            gemini_response = ai_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )
            reply_text = gemini_response.text

            # 5. حفظ رد البوت في Supabase
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "model",
                "content": reply_text
            }).execute()

            # 6. إرسال الرد للديسكورد (مع تقسيم الرسالة لو كانت طويلة جداً)
            if len(reply_text) > 2000:
                for i in range(0, len(reply_text), 2000):
                    await message.reply(reply_text[i:i+2000])
            else:
                await message.reply(reply_text)

        except Exception as e:
            print(f"Error: {e}")
            await message.reply("معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا. حاول مرة ثانية!")

# تشغيل البوت
client.run(DISCORD_TOKEN)
