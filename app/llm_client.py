from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage,SystemMessage
from .config import GOOGLE_API_KEY

class LLMClient:
    def __init__(self,model: str = "gemini-2.5-flash",temperature: float=0.2):
        self.llm=ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            api_key=GOOGLE_API_KEY
        )


    def invoke(self,prompt:str,system_prompt:str|None=None)-> str:
        """
        Generate text from a user prompt, optionally including a system prompt.

        Args:
            prompt (str): The main user prompt.
            system_prompt (str | None): Optional system instruction for context.

        Returns:
            str: Generated text from Gemini 2.5 Flash.
        """
        #Build message List
        messages=[]
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        #Invoke LLM
        response=self.llm.invoke(messages)
        return response.content