import os
import discord
from supabase import create_client, Client
from google import genai
from google.genai import types

# 1. المتغيرات
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# 2. إعداد الاتصالات
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

SYSTEM_INSTRUCTION = """أنت مساعد دراسي ذكي ومفيد لأحمد، طالب في الصف التاسع في طرابلس، ليبيا.
تساعده في فهم الدروس، حل التمارين، وتنظيم وقته للدراسة.
لهجتك ليبية محببة وواضحة.
أمامك ملف الكتاب المدرسي الكامل مرفق مع المحادثة. اعتمد عليه كمرجع أساسي وأول لإجابة جميع أسئلة الطالب واستخراج الحلول والتمارين منه بدقة."""

# متغير عام لحفظ مرجع الكتاب في ذاكرة البوت
uploaded_book_file = None

@client.event
async def on_ready():
    global uploaded_book_file
    print(f'✅ البوت {client.user} جاهز ومتصل!')
    
    # رفع كتاب الـ PDF لـ Gemini عند تشغيل البوت
    book_path = "math_grade9.pdf"
    if os.path.exists(book_path):
        try:
            print("⏳ جاري رفع الكتاب المدرسي الكامل إلى Gemini...")
            uploaded_book_file = ai_client.files.upload(file=book_path)
            print(f"🎉 تم تحميل الكتاب بنجاح: {uploaded_book_file.name}")
        except Exception as e:
            print(f"❌ خطأ أثناء رفع ملف الكتاب: {e}")
    else:
        print("⚠️ ملف book.pdf غير موجود في مجلد المشروع، حايخدم البوت بدون كتاب مرفق.")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        if not user_msg:
            return

        try:
            # 1. حفظ رسالة المستخدم في Supabase
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "user",
                "content": user_msg
            }).execute()

            # 2. جلب آخر 6 رسائل من ذاكرة المحادثة
            response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(6).execute()
            history_data = reversed(response.data)
            
            contents = []
            
            # إرفاق الكتاب الكامل في بداية المحادثة ليكون مرجعاً لـ Gemini
            if uploaded_book_file:
                contents.append(uploaded_book_file)

            # إضافة سجل المحادثة
            for row in history_data:
                contents.append(
                    types.Content(
                        role=row["role"], 
                        parts=[types.Part.from_text(text=row["content"])]
                    )
                )

            # 3. توليد الرد من Gemini 3.6 Flash اعتماداً على الكتاب والذاكرة
            gemini_response = ai_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )
            reply_text = gemini_response.text

            # 4. حفظ رد البوت في Supabase
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "model",
                "content": reply_text
            }).execute()

            # 5. إرسال الرد للديسكورد
            if len(reply_text) > 2000:
                for i in range(0, len(reply_text), 2000):
                    await message.reply(reply_text[i:i+2000])
            else:
                await message.reply(reply_text)

        except Exception as e:
            print(f"Error: {e}")
            await message.reply("معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا. حاول مرة ثانية!")

client.run(DISCORD_TOKEN)
