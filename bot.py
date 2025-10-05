import discord
from discord.ext import commands, tasks
import fitz
from openai import OpenAI
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from typing import List, Literal, Annotated
import threading
from flask import Flask

class Question(BaseModel):
    question: str
    choice_A: str
    choice_B: str
    choice_C: str
    choice_D: str
    choice_E: str
    correct_answer: Literal["A", "B", "C", "D", "E"]
    correct_answer_explanation: str

class Quiz(BaseModel):
    questions: Annotated[List[Question], Field(min_length=50, max_length=50)]

load_dotenv() 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_KEY")
ALLOWED_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

prompt = os.getenv("CUSTOM_PROMPT", "You are making 50 multiple-choice test questions. \
                Each question has 5 answer choices (A, B, C, D, E). Provide the correct answer letter \
                and an explanation for each question.")
default_prompt = "You are making 50 multiple-choice test questions. \
                Each question has 5 answer choices (A, B, C, D, E). Provide the correct answer letter \
                and an explanation for each question."
upload_desc = os.getenv("CUSTOM_UPLOAD_DESC", "Upload a pdf.")
end_desc = os.getenv("CUSTOM_END_DESC", "End class.")
generate_desc = os.getenv("CUSTOM_GENERATE_DESC", "Generate a quiz.")
question_desc = os.getenv("CUSTOM_QUESTION_DESC", "Get the current question.")
answer_desc = os.getenv("CUSTOM_ANSWER_DESC", "Send in your answer.")
nextquestion_desc = os.getenv("CUSTOM_NEXTQUESTION_DESC", "Move to the next question.")
shownextquestion_desc = os.getenv("CUSTOM_SHOWNEXTQUESTION_DESC", "Move to the next question and show the question.")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
client = OpenAI(api_key=OPENAI_API_KEY)

quiz_session = {
    "active": False,
    "text": "",
    "questions": [],
    "current": 0,
    "last_activity": None
}

app = Flask("")

@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

@bot.tree.command(name="upload", description=upload_desc)
async def upload(interaction: discord.Interaction, file: discord.Attachment):
    global quiz_session

    if quiz_session["active"]:
        await interaction.response.send_message("❌ A session is already running! End it with `/end` before uploading a new PDF.")
        return
    
    await interaction.response.defer(thinking=True)  
    
    if not file.filename.endswith(".pdf"):
        await interaction.followup.send("⚠️ Please upload a PDF file.")
        return
    
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

    await interaction.followup.send("✅ PDF loaded! Use `/generate` to create a question bank.")

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
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="end", description=end_desc)
async def end(interaction: discord.Interaction):
    global quiz_session
    quiz_session.update({
        "active": False,
        "text": "",
        "questions": [],
        "current": 0,
        "last_activity": None
    })
    await interaction.response.send_message("🛑 Session ended.")

@bot.tree.command(name="generate", description=generate_desc)
async def generate(interaction: discord.Interaction):
    global quiz_session
    
    if not quiz_session["active"]:
        await interaction.response.send_message("❌ No session active. Upload a PDF first with `/upload`.")
        return
    
    await interaction.response.defer(thinking=True)
    text = quiz_session["text"]

    response = client.responses.parse(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": prompt },
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
    
    await interaction.followup.send("Generated 50 questions! Use /question to get one.")

@bot.tree.command(name="defaultpromptgenerate", description=generate_desc)
async def default_prompt_generate(interaction: discord.Interaction):
    global quiz_session
    
    if not quiz_session["active"]:
        await interaction.response.send_message("❌ No session active. Upload a PDF first with `/upload`.")
        return
    
    await interaction.response.defer(thinking=True)
    text = quiz_session["text"]

    response = client.responses.parse(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": default_prompt },
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
    
    await interaction.followup.send("Generated 50 questions! Use /question to get one.")

@bot.tree.command(name="question", description=question_desc)
async def question(interaction: discord.Interaction):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await interaction.response.send_message("❌ No active quiz. Use `/upload` and `/generate` first.")
        return
    
    current = quiz_session["current"]
    questions = quiz_session["questions"]
    
    if current >= len(questions):
        await interaction.response.send_message("🎉 Quiz finished! Use `/generate` to make new questions or `/end` to close session.")
        return
    
    q = questions[current]
    msg = f"""
    **Q{current+1}**: {q.question}

    A) {q.choice_A}
    B) {q.choice_B}
    C) {q.choice_C}
    D) {q.choice_D}
    E) {q.choice_E}
    """

    quiz_session["last_activity"] = datetime.now(timezone.utc)
    await interaction.response.send_message(msg)

@bot.tree.command(name="answer", description=answer_desc)
async def answer(interaction: discord.Interaction, choice: str):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await interaction.response.send_message("❌ No active quiz.")
        return
    
    current = quiz_session["current"]
    questions = quiz_session["questions"]
    
    if current >= len(questions):
        await interaction.response.send_message("🎉 Quiz finished! No more questions.")
        return
    
    q = questions[current]
    if choice.upper() == q.correct_answer:
        await interaction.response.send_message(f"✅ Correct! {q.correct_answer_explanation}")
    else:
        await interaction.response.send_message(f"❌ Wrong. Correct answer is {q.correct_answer} — {q.correct_answer_explanation}")
    
    quiz_session["last_activity"] = datetime.now(timezone.utc)

@bot.tree.command(name="nextquestion", description=nextquestion_desc)
async def nextquestion(interaction: discord.Interaction):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await interaction.response.send_message("❌ No active quiz.")
        return
    
    quiz_session["current"] += 1
    
    if quiz_session["current"] >= len(quiz_session["questions"]):
        await interaction.response.send_message("🎉 All questions answered! Use `/generate` to create more or `/end` to close session.")
    else:
        await interaction.response.send_message(f"➡️ Moving to Question {quiz_session['current']+1}. Use `/question` to view it.")
    
    quiz_session["last_activity"] = datetime.now(timezone.utc)

@bot.tree.command(name="shownextquestion", description=shownextquestion_desc)
async def nextquestion(interaction: discord.Interaction):
    global quiz_session
    
    if not quiz_session["active"] or not quiz_session["questions"]:
        await interaction.response.send_message("❌ No active quiz. Use `/upload` and `/generate` first.")
        return
    
    quiz_session["current"] += 1
    current = quiz_session["current"]
    questions = quiz_session["questions"]
    
    if current >= len(questions):
        await interaction.response.send_message("🎉 Quiz finished! Use `/generate` to make new questions or `/end` to close session.")
        return
    
    q = questions[current]
    msg = f"""
    **Q{current+1}**: {q.question}

    A) {q.choice_A}
    B) {q.choice_B}
    C) {q.choice_C}
    D) {q.choice_D}
    E) {q.choice_E}
    """

    quiz_session["last_activity"] = datetime.now(timezone.utc)
    await interaction.response.send_message(msg)

keep_alive()
bot.run(DISCORD_TOKEN)