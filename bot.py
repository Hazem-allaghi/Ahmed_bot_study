import os
import discord
import asyncio
import edge_tts
from supabase import create_client, Client
from google import genai
from google.genai import types

# 1. المتغيرات ومفاتيح البيئة
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
أمامك ملف الكتاب المدرسي الكامل المرفق في المحادثة، استخدمه لاستخراج الحلول والتمارين بدقة كمرجع أساسي."""

# متغير عام لحفظ مرجع الكتاب
uploaded_book_file = None

@client.event
async def on_ready():
    global uploaded_book_file
    print(f'✅ البوت {client.user} جاهز ومتصل، ويدعم الصوت!')
    
    # تحميل ملف الـ PDF لـ Gemini عند بدء التشغيل
    book_path = "math_grade9.pdf" # تأكد من اسم الكتاب هنا
    if os.path.exists(book_path):
        try:
            print("⏳ جاري رفع الكتاب المدرسي الكامل إلى Gemini...")
            uploaded_book_file = ai_client.files.upload(file=book_path)
            print(f"🎉 تم تحميل الكتاب بنجاح: {uploaded_book_file.name}")
        except Exception as e:
            print(f"❌ خطأ أثناء رفع ملف الكتاب: {e}")
    else:
        print(f"⚠️ ملف {book_path} غير موجود. البوت سيخدم بدونه.")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        # استخراج النص إن وجد
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        # التأكد إذا كان أحمد باعت رسالة صوتية
        uploaded_audio_part = None
        if message.attachments:
            for att in message.attachments:
                # لو المرفق ملف صوتي (Voice Note)
                if att.content_type and att.content_type.startswith('audio'):
                    audio_path = f"temp_{message.id}.ogg"
                    await att.save(audio_path)
                    try:
                        # رفع الصوت لـ Gemini مع تحديد نوع الملف
                        gemini_audio = ai_client.files.upload(
                            file=audio_path,
                            config={'mime_type': 'audio/ogg'}
                        )
                        uploaded_audio_part = gemini_audio
                    except Exception as e:
                        print(f"Error uploading audio to Gemini: {e}")
                    finally:
                        if os.path.exists(audio_path):
                            os.remove(audio_path) # حذف الملف المؤقت
                    break

        if not user_msg and not uploaded_audio_part:
            return

        db_msg = user_msg if user_msg else "[أحمد أرسل رسالة صوتية]"

        try:
            # 1. حفظ رسالة المستخدم في قاعدة البيانات
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "user",
                "content": db_msg
            }).execute()

            # 2. جلب آخر رسائل من الذاكرة
            response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(6).execute()
            history_data = reversed(response.data)
            
            contents = []
            
            # إرفاق الكتاب إن وجد
            if uploaded_book_file:
                contents.append(uploaded_book_file)

            # إرفاق الرسالة الصوتية اللي بعثها أحمد (إن وجدت)
            if uploaded_audio_part:
                contents.append(uploaded_audio_part)

            # تجهيز الذاكرة
            for row in history_data:
                if row["content"] != "[أحمد أرسل رسالة صوتية]":
                    contents.append(
                        types.Content(
                            role=row["role"], 
                            parts=[types.Part.from_text(text=row["content"])]
                        )
                    )
            
            # إضافة نص الرسالة الحالية لو كان باعت نص مع الصوت
            if user_msg:
                contents.append(user_msg)

            # 3. توليد الرد من Gemini (بالطريقة المستقرة)
            gemini_response = ai_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )
            reply_text = gemini_response.text

            # 4. حفظ الرد في قاعدة البيانات
            supabase.table('chat_history').insert({
                "user_id": user_id,
                "role": "model",
                "content": reply_text
            }).execute()

            # 5. تحويل الرد النصي إلى رسالة صوتية
            audio_reply_path = f"reply_{message.id}.mp3"
            communicate = edge_tts.Communicate(reply_text, "ar-LY-OmarNeural")
            await communicate.save(audio_reply_path)

            # 6. إرسال النص + الرسالة الصوتية لأحمد
            if len(reply_text) > 2000:
                await message.reply(reply_text[:1990] + "...", file=discord.File(audio_reply_path))
            else:
                await message.reply(reply_text, file=discord.File(audio_reply_path))
                
            # تنظيف السيرفر
            if os.path.exists(audio_reply_path):
                os.remove(audio_reply_path)

        except Exception as e:
            print(f"Error: {e}")
            await message.reply("معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا. حاول مرة ثانية!")

client.run(DISCORD_TOKEN)
