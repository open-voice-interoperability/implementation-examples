# load the large language model file
from llama_cpp import Llama
LLM = Llama(model_path="./llama-2-7b-chat.ggmlv3.q8_0.bin")

# create a text prompt
prompt = "Q: What are the names of the days of the week? A:"

# generate a response (takes several seconds)
output = LLM(prompt)

# display the response
print(output["choices"][0]["text"])