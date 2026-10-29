import anthropic

client = anthropic.Client()

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