from gpt4all import GPT4All

# see https://docs.gpt4all.io/ for gpt4all documentation
# you can install gpt4all from https://pypi.org/project/gpt4all/#files

# some models that can be tried
#model = GPT4All("orca-mini-3b.ggmlv3.q4_0.bin")
#model = GPT4All("orca-mini-7b.ggmlv3.q4_0.bin")
#orca-mini-13b.ggmlv3.q4_0.bin
#ggml-replit-code-v1-3b.bin
#model = GPT4All("llama-2-7b-chat.ggmlv3.q4_0.bin")
#model = GPT4All("ggml-gpt4all-j-v1.3-groovy.bin")
#model = GPT4All("ggml-model-gpt4all-falcon-q4_0.bin")

class NLP:
    def __init__(self):
        self.model = GPT4All("ggml-model-gpt4all-falcon-q4_0.bin")
        self.language = "en"
        self.system_template = "if you can't answer apologize"
        self.prompt_template = 'USER: {0}\nASSISTANT: '
        # increase to increase creativity
        self.temperature = .1
        # randomly sample from the top_k most likely tokens 
        self.top_k = 2
        # randomly sample from each generation step from top most likely tokens whose probabilities add up to this value
        self.top_p = .9
        # number of prompt tokens to process in parallel. Increase to speed up inference
        self.n_batch = 30
        self.current_result = ""
        self.max_tokens = 100
        
    def answer_question(self,text):
        result = self.model.generate(self.system_template + text, 
                        temp = self.temperature,
                        top_k = self.top_k,
                        top_p = self.top_p,
                        max_tokens = self.max_tokens)
        print("LLM result" + result)
        self.current_result = result
        print("LLM current result" + self.current_result)

    def get_current_result(self):
        return(self.current_result)
    
