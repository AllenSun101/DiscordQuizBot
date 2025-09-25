import discord
from discord.ext import commands, tasks
import fitz
from openai import OpenAI
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from typing import List, Literal, Annotated

class Question(BaseModel):
    question: str
    choice_A: str
    choice_B: str
    choice_C: str
    choice_D: str
    correct_answer: Literal["A", "B", "C", "D"]
    correct_answer_explanation: str

class Quiz(BaseModel):
    questions: Annotated[List[Question], Field(min_length=50, max_length=50)]

load_dotenv() 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_KEY")
ALLOWED_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)
client = OpenAI(api_key=OPENAI_API_KEY)

quiz_session = {
    "active": False,
    "text": "",
    "questions": [],
    "current": 0,
    "last_activity": None
}

@bot.command()
async def upload(ctx):
    global quiz_session

    if quiz_session["active"]:
        await ctx.send("❌ A session is already running! End it with `/end` before uploading a new PDF.")
        return
    
    if ctx.message.attachments:
        file = ctx.message.attachments[0]
        await file.save("temp.pdf")
        doc = fitz.open("temp.pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        
        quiz_session["text"] = text
        quiz_session["questions"] = []
        quiz_session["current"] = 0
        quiz_session["last_activity"] = datetime.now(timezone.utc)
        quiz_session["active"] = True

        await ctx.send("✅ PDF loaded! Use `/generate` to create a question bank.")
    else:
        await ctx.send("❌ Please attach a PDF file.")

@tasks.loop(minutes=5)
async def check_timeout():
    global quiz_session
    if quiz_session["active"]:
        if datetime.now(timezone.utc) - quiz_session["last_activity"] > timedelta(minutes=30):
            quiz_session["active"] = False
            quiz_session["text"] = ""
            quiz_session["questions"] = []
            quiz_session["current"] = 0
            quiz_session["last_activity"] = None
            # You might want to broadcast this to a channel instead of ctx.send
            print("Session ended due to inactivity.")

@bot.event
async def on_ready():
    check_timeout.start()
    print(f"Logged in as {bot.user}")

@bot.command()
async def end(ctx):
    global quiz_session
    quiz_session.update({
        "active": False,
        "text": "",
        "questions": [],
        "current": 0,
        "last_activity": None
    })
    await ctx.send("🛑 Session ended.")

@bot.command()
async def generate(ctx):
    global quiz_session
    
    if not quiz_session["active"]:
        await ctx.send("❌ No session active. Upload a PDF first with `/upload`.")
        return
    
    text = quiz_session["text"]

    response = client.responses.parse(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": "You are making 50 multiple-choice test questions. \
                Each question has 4 answer choices (A, B, C, D). Provide the correct answer letter \
                and an explanation for each question. The questions should be challenging and thorough."},
            {
                "role": "user",
                "content": f"Base the questions strictly on this text: {text}",
            },
        ],
        
        text_format=Quiz,
    )

    generated_questions = response.output_parsed.questions
    quiz_session["questions"] = generated_questions
    quiz_session["current"] = 0
    quiz_session["last_activity"] = datetime.now(timezone.utc)
    
    await ctx.send("Generated 50 questions! Use /question to get one.")

@bot.command()
async def question(ctx):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await ctx.send("❌ No active quiz. Use `/upload` and `/generate` first.")
        return
    
    current = quiz_session["current"]
    questions = quiz_session["questions"]
    
    if current >= len(questions):
        await ctx.send("🎉 Quiz finished! Use `/generate` to make new questions or `/end` to close session.")
        return
    
    q = questions[current]
    msg = f"""
    **Q{current+1}**: {q.question}

    A) {q.choice_A}
    B) {q.choice_B}
    C) {q.choice_C}
    D) {q.choice_D}
    """

    quiz_session["last_activity"] = datetime.now(timezone.utc)
    await ctx.send(msg)

@bot.command()
async def answer(ctx, choice: str):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await ctx.send("❌ No active quiz.")
        return
    
    current = quiz_session["current"]
    questions = quiz_session["questions"]
    
    if current >= len(questions):
        await ctx.send("🎉 Quiz finished! No more questions.")
        return
    
    q = questions[current]
    if choice.upper() == q.correct_answer:
        await ctx.send(f"✅ Correct! {q.correct_answer_explanation}")
    else:
        await ctx.send(f"❌ Wrong. Correct answer is {q.correct_answer} — {q.correct_answer_explanation}")
    
    quiz_session["last_activity"] = datetime.now(timezone.utc)

@bot.command()
async def nextquestion(ctx):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await ctx.send("❌ No active quiz.")
        return
    
    quiz_session["current"] += 1
    
    if quiz_session["current"] >= len(quiz_session["questions"]):
        await ctx.send("🎉 All questions answered! Use `/generate` to create more or `/end` to close session.")
    else:
        await ctx.send(f"➡️ Moving to Question {quiz_session['current']+1}. Use `/question` to view it.")
    
    quiz_session["last_activity"] = datetime.now(timezone.utc)

bot.run(DISCORD_TOKEN)