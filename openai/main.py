from openai import OpenAI
client = OpenAI()

response = client.responses.create(
    model = "o4-mini"
    input = "Create a story"
)

print(response.output_text)