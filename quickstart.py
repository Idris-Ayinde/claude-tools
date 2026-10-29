from dotenv import load_dotenv
import os
import anthropic

load_dotenv()

# Not used: anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment
# on its own, and load_dotenv() above has already put it there.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=1000,
    messages=[
        {
            "role": "user",
            "content": "What should I search for to find the latest developments in renewable energy?",
        }
    ],
)

for block in message.content:
    if block.type == "text":
        print(block.text)