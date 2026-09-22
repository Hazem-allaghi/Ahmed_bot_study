import os
import asyncio
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

# 3. التعليمات الصارمة
SYSTEM_INSTRUCTION = """أنت مساعد دراسي ذكي ومفيد لأحمد، طالب في الصف التاسع في طرابلس، ليبيا.
تساعده في فهم الدروس، حل التمارين، وتنظيم وقته للدراسة.
لهجتك ليبية محببة وواضحة.

🚨 قوانين صارمة جداً يجب عليك اتباعها:
1. الإجابات من الكتاب فقط: لديك وصول لكتاب المادة المرفق. يجب عليك الإجابة على أي سؤال دراسي من محتوى هذا الكتاب حصراً.
2. منع الهلوسة نهائياً: ممنوع منعاً باتاً اختراع إجابات، أو استنتاج معلومات غير موجودة بوضوح في الكتاب، أو استخدام معلومات من خارجه.
3. الاعتراف بعدم المعرفة: إذا سألك الطالب سؤالاً دراسياً ولم تجد إجابته بشكل مباشر وصريح في الكتاب المرفق، يجب أن تعتذر بلطف وتقول: "معليش يا أحمد، دورت في كتاب المادة ومالقيتش إجابة واضحة لسؤالك، حاول تتأكد من السؤال أو تسأل الأستاذ".
4. المحادثة العادية: يمكنك استخدام معرفتك العامة فقط في الدردشة العادية والتشجيع وتنسيق الوقت."""

# قاموس ديناميكي لحفظ مراجع الكتب بعد رفعها
uploaded_books = {}

@client.event
async def on_ready():
    global uploaded_books
    print(f'✅ البوت {client.user} جاهز ومتصل!')
    
    if not uploaded_books:
        print("⏳ جاري البحث عن الكتب ورفعها تلقائياً...")
        
        pdf_files = [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
        
        for book_name in pdf_files:
            channel_key = book_name.lower().replace('.pdf', '')
            try:
                uploaded_file = ai_client.files.upload(file=book_name)
                uploaded_books[channel_key] = uploaded_file
                print(f"🎉 تم ربط الكتاب: {book_name} ليتم استخدامه في القناة التي تحتوي على الاسم: {channel_key}")
            except Exception as e:
                print(f"⚠️ فشل رفع الكتاب {book_name}: {e}")
                
        print("📚 تم الانتهاء من تجهيز جميع الكتب الموجودة!")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    # استخراج اسم القناة
    channel_name = message.channel.name.lower() if not isinstance(message.channel, discord.DMChannel) else "خاص"
    
    # التحقق هل القناة هذي مربوطة بكتاب أو لا
    is_study_channel = any(key in channel_name for key in uploaded_books.keys())

    # البوت حيرد لو: القناة مخصصة للقراية، أو رسالة خاصة، أو درتله منشن
    if is_study_channel or client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_msg = message.clean_content.replace(f'@{client.user.name}', '').strip()
        user_id = str(message.author.id)
        
        # تحديد الكتاب بناءً على اسم القناة تلقائياً
        selected_book = None
        for key, book_file in uploaded_books.items():
            if key in channel_name:
                selected_book = book_file
                break

        # معالجة الملف الصوتي إن وجد
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
            # جلب المحادثات السابقة
            history_data = []
            try:
                response = supabase.table('chat_history').select("*").eq("user_id", user_id).order("created_at", desc=True).limit(6).execute()
                history_data = list(reversed(response.data))
            except Exception as e:
                print(f"Supabase Fetch Error: {e}")

            # حفظ رسالة المستخدم
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "user",
                    "content": db_msg
                }).execute()
            except Exception as e:
                print(f"Supabase Insert Error: {e}")

            # بناء الذاكرة (History)
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

            # إنشاء جلسة المحادثة
            chat = ai_client.chats.create(
                model='gemini-3.6-flash',
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
                history=history_contents
            )

            # تجهيز الطلب
            current_message_payload = []
            
            if selected_book:
                current_message_payload.append(selected_book)
                
            if gemini_audio_file:
                current_message_payload.append(gemini_audio_file)
                
            if user_msg:
                current_message_payload.append(user_msg)
            elif gemini_audio_file and not user_msg:
                current_message_payload.append("استمع للرسالة الصوتية وأجب عليها بالاعتماد على الكتاب المرفق فقط.")

            # إرسال الطلب وتنفيذه في الخلفية
            gemini_response = await asyncio.to_thread(chat.send_message, current_message_payload)
            reply_text = gemini_response.text

            # إضافة ملاحظة لو القناة مش مربوطة بكتاب
            if not selected_book and "خاص" not in channel_name:
                reply_text += "\n\n*(ملاحظة من البوت: انتبه يا أحمد، القناة هذي مش مربوطة بكتاب، تأكد من اسم القناة باش نقدر نجاوبك من المنهج!)*"

            # حفظ الرد
            try:
                supabase.table('chat_history').insert({
                    "user_id": user_id,
                    "role": "model",
                    "content": reply_text
                }).execute()
            except Exception as e:
                print(f"Supabase Save Reply Error: {e}")

            # توليد الصوت وإرسال الرد
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

        except discord.errors.NotFound:
            print("⚠️ ملاحظة: البوت حاول الرد لكن القناة أو الرسالة تم مسحها.")
        except Exception as e:
            print(f"General Error: {e}")
            try:
                await message.reply(f"معليش يا أحمد، واجهتني مشكلة تقنية صغيرة توا، دقيقة ونكون معاك!")
            except:
                pass

client.run(DISCORD_TOKEN)
