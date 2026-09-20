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
إذا تم إرفاق كتاب أو ملف في المحادثة، اعتمد عليه كمرجع أساسي لإجابة الطالب."""

# متغير عام لحفظ مرجع الكتاب
uploaded_book_file = None

@client.event
async def on_ready():
    global uploaded_book_file
    print(f'✅ البوت {client.user} جاهز ومتصل، ويدعم الصوت والنص!')
    
    book_path = "math_grade9.pdf" # تأكد من اسم الملف في GitHub
    if os.path.exists(book_path):
        try:
            print("⏳ جاري رفع الكتاب المدرسي إلى Gemini...")
            uploaded_book_file = ai_client.files.upload(file=book_path)
            print(f"🎉 تم تحميل الكتاب بنجاح: {uploaded_book_file.name}")
        except Exception as e:
            print(f"⚠️ فشل رفع الكتاب، وسيعمل البوت بدونه: {e}")
    else:
        print(f"⚠️ الملف {book_path} غير موجود في المجلد. سيعمل البوت بشكل طبيعي بدون كتاب.")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    # الرد فقط عند المنشن أو في الرسائل الخاصة (DM)
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        # معالجة الملف الصوتي إن وجد
        audio_part = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and att.content_type.startswith('audio'):
                    audio_path = f"temp_{message.id}.ogg"
                    await att.save(audio_path)
                    try:
                        gemini_audio = ai_client.files.upload(
                            file=audio_path,
                            config={'mime_type': 'audio/ogg'}
                        )
                        # التعديل الصحيح لاستدعاء Part.from_uri
                        audio_part = types.Part.from_uri(
                            gemini_audio.uri,
                            mime_type=gemini_audio.mime_type or 'audio/ogg'
                        )
                    except Exception as e:
                        print(f"Error uploading audio: {e}")
                    finally:
                        if os.path.exists(audio_path):
                            os.remove(audio_path)
                    break

        if not user_msg and not audio_part:
            return

        db_msg = user_msg if user_msg else "[رسالة صوتية]"

        try:
            # 1. جلب المحادثات السابقة من Supabase
            history_data = []
            try:
                response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(6).execute()
                history_data = list(reversed(response.data))
            except Exception as e:
                print(f"Supabase Fetch Error: {e}")

            # 2. حفظ رسالة المستخدم الحالية
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "user",
                    "content": db_msg
                }).execute()
            except Exception as e:
                print(f"Supabase Insert Error: {e}")

            # 3. بناء قائمة Contents
            contents = []

            # إضافة المحادثات السابقة
            for row in history_data:
                if row.get("content") and str(row["content"]).strip():
                    contents.append(
                        types.Content(
                            role=row["role"],
                            parts=[types.Part.from_text(text=row["content"])]
                        )
                    )

            # تجهيز الطلب الحالي للمستخدم
            current_parts = []

            # إضافة الكتاب كـ Part إن وجد (التعديل الصحيح هنا)
            if uploaded_book_file:
                current_parts.append(
                    types.Part.from_uri(
                        uploaded_book_file.uri,
                        mime_type=uploaded_book_file.mime_type or 'application/pdf'
                    )
                )

            # إضافة الصوت إن وجد
            if audio_part:
                current_parts.append(audio_part)

            # إضافة النص
            if user_msg:
                current_parts.append(types.Part.from_text(text=user_msg))
            elif audio_part and not user_msg:
                current_parts.append(types.Part.from_text(text="استمع للرسالة الصوتية وأجب عليها."))

            contents.append(
                types.Content(
                    role="user",
                    parts=current_parts
                )
            )

            # 4. طلب الإجابة من Gemini
            gemini_response = ai_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )
            reply_text = gemini_response.text

            # 5. حفظ الرد في Supabase
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "model",
                    "content": reply_text
                }).execute()
            except Exception as e:
                print(f"Supabase Save Reply Error: {e}")

            # 6. توليد الصوت وإرسال الرد
            audio_reply_path = f"reply_{message.id}.mp3"
            try:
                communicate = edge_tts.Communicate(reply_text, "ar-LY-OmarNeural")
                await communicate.save(audio_reply_path)
                
                if len(reply_text) > 2000:
                    await message.reply(reply_text[:1990] + "...", file=discord.File(audio_reply_path))
                else:
                    await message.reply(reply_text, file=discord.File(audio_reply_path))
            except Exception as sound_err:
                print(f"TTS Error: {sound_err}")
                if len(reply_text) > 2000:
                    await message.reply(reply_text[:1990] + "...")
                else:
                    await message.reply(reply_text)
            finally:
                if os.path.exists(audio_reply_path):
                    os.remove(audio_reply_path)

        except Exception as e:
            print(f"General Error: {e}")
            await message.reply("معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا. حاول مرة ثانية!")

client.run(DISCORD_TOKEN)
