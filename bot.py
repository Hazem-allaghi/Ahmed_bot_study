import os
import discord
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

# 3. التعليمات الصارمة لمنع الهلوسة
SYSTEM_INSTRUCTION = """أنت مساعد دراسي ذكي ومفيد لأحمد، طالب في الصف التاسع في طرابلس، ليبيا.
تساعده في فهم الدروس، حل التمارين، وتنظيم وقته للدراسة.
لهجتك ليبية محببة وواضحة.

🚨 قوانين صارمة جداً يجب عليك اتباعها:
1. الإجابات من الكتب فقط: لديك وصول لعدة كتب مدرسية مرفقة. يجب عليك الإجابة على أي سؤال علمي أو دراسي من محتوى هذه الكتب حصراً.
2. منع الهلوسة نهائياً: ممنوع منعاً باتاً اختراع إجابات، أو استنتاج معلومات غير موجودة بوضوح في الكتب، أو استخدام معلومات من خارج المقررات المرفقة.
3. الاعتراف بعدم المعرفة: إذا سألك الطالب سؤالاً دراسياً ولم تجد إجابته بشكل مباشر وصريح في الكتب المرفقة، يجب أن تعتذر بلطف وتقول: "معليش يا أحمد، دورت في الكتب اللي عندي ومالقيتش إجابة واضحة لسؤالك، حاول تتأكد من السؤال أو تسأل الأستاذ".
4. المحادثة العادية: يمكنك استخدام معرفتك العامة فقط في الدردشة العادية، الترحيب، النصائح العامة لتنظيم الوقت، والتشجيع المستمر."""

# 4. قائمة أسماء الكتب المدرسية
BOOKS_LIST = [
    "arabic_grade9.pdf",
    "computer_Science_grade9.pdf",
    "geography_grade9.pdf",
    "history_grade9.pdf",
    "islamic_grade9.pdf",
    "math_grade9.pdf",
    "national_grade9.pdf",
    "science_grade9.pdf",
    "science_student_p1_garde9.pdf",
    "science_student_p2_garde9.pdf"
]

# مصفوفة لحفظ مراجع الكتب اللي تم رفعها
uploaded_books = []

@client.event
async def on_ready():
    global uploaded_books
    print(f'✅ البوت {client.user} جاهز ومتصل!')
    
    # التأكد من عدم إعادة رفع الكتب إذا فصل البوت واتصل من جديد
    if not uploaded_books:
        print("⏳ جاري رفع الكتب المدرسية إلى Gemini... (هذه العملية قد تستغرق بعض الوقت)")
        for book_name in BOOKS_LIST:
            if os.path.exists(book_name):
                try:
                    uploaded_file = ai_client.files.upload(file=book_name)
                    uploaded_books.append(uploaded_file)
                    print(f"🎉 تم تحميل الكتاب بنجاح: {book_name}")
                except Exception as e:
                    print(f"⚠️ فشل رفع الكتاب {book_name}: {e}")
            else:
                print(f"⚠️ الملف {book_name} غير موجود في المجلد. سيتم تخطيه.")
        print("📚 تم الانتهاء من تجهيز جميع الكتب!")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        # 1. معالجة الملف الصوتي إن وجد
        gemini_audio_file = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and att.content_type.startswith('audio'):
                    audio_path = f"temp_{message.id}.ogg"
                    await att.save(audio_path)
                    try:
                        gemini_audio_file = ai_client.files.upload(
                            file=audio_path,
                            config={'mime_type': 'audio/ogg'}
                        )
                    except Exception as e:
                        print(f"Error uploading audio: {e}")
                    finally:
                        if os.path.exists(audio_path):
                            os.remove(audio_path)
                    break

        if not user_msg and not gemini_audio_file:
            return

        db_msg = user_msg if user_msg else "[رسالة صوتية]"

        try:
            # 2. جلب المحادثات السابقة
            history_data = []
            try:
                response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(6).execute()
                history_data = list(reversed(response.data))
            except Exception as e:
                print(f"Supabase Fetch Error: {e}")

            # 3. حفظ رسالة المستخدم الحالية
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "user",
                    "content": db_msg
                }).execute()
            except Exception as e:
                print(f"Supabase Insert Error: {e}")

            # 4. بناء الذاكرة (History)
            history_contents = []
            last_role = None
            for row in history_data:
                content_text = row.get("content", "").strip()
                current_role = row["role"]
                
                if not content_text:
                    continue
                    
                if current_role == last_role and history_contents:
                    history_contents[-1].parts[0].text += f"\n{content_text}"
                else:
                    history_contents.append(
                        types.Content(
                            role=current_role,
                            parts=[types.Part.from_text(text=content_text)]
                        )
                    )
                    last_role = current_role

            # 5. إنشاء جلسة المحادثة
            chat = ai_client.chats.create(
                model='gemini-3.6-flash',
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
                history=history_contents
            )

            # 6. تجهيز الطلب الحالي 
            current_message_payload = []
            
            # تمرير كل الكتب المرفوعة دفعة واحدة للنموذج
            if uploaded_books:
                current_message_payload.extend(uploaded_books)
                
            if gemini_audio_file:
                current_message_payload.append(gemini_audio_file)
                
            if user_msg:
                current_message_payload.append(user_msg)
            elif gemini_audio_file and not user_msg:
                current_message_payload.append("استمع للرسالة الصوتية وأجب عليها بالاعتماد على الكتب المدرسية المرفقة فقط.")

            # 7. إرسال الطلب
            gemini_response = chat.send_message(current_message_payload)
            reply_text = gemini_response.text

            # 8. حفظ الرد
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "model",
                    "content": reply_text
                }).execute()
            except Exception as e:
                print(f"Supabase Save Reply Error: {e}")

            # 9. توليد الصوت وإرسال الرد
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
            await message.reply(f"معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا، دقيقة ونكون معاك!")

client.run(DISCORD_TOKEN)
