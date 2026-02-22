"""
Prompt Class is implemented here.
"""
from typing import Optional

class Prompt:
    def __init__(
            self, 
            version: str, 
            datetime: str, 
            prompt_text: str, 
            description: str,
            model: str, 
            inputs: Optional[str] = None, 
            llm_result: Optional[str] = None, 
            nickname: Optional[str] = None) -> None:
        """
        Initialize a prompt object

        Args:
            version: Prompt version
            datetime: Date and time when the inference took place
            prompt_text: String of the prompt
            description: A simple description about the version of the prompt
            model: Which model was used for the inference
            inputs: Any additional inputs that were sent alongside the prompt (like JSONS, documents, etc.)
            llm_result: Result text from the model
            nickname: An optional nickname for the prompt version 
        """
        
        self.version = version
        self.datetime = datetime
        self.prompt_text = prompt_text
        self. description = description
        self.model = model
        self.inputs = inputs
        self.llm_result = llm_result
        self.nickname = nickname


class SytemPrompt(Prompt):
    def __init__(self, 
                 version: str, 
                 datetime: str, 
                 prompt_text: str, 
                 description: str, 
                 model: str, 
                 inputs: str | None = None, 
                 llm_result: str | None = None, 
                 nickname: str | None = None) -> None:
        super().__init__(version, datetime, prompt_text, description, model, inputs, llm_result, nickname)


class UserPrompt(Prompt):
    def __init__(self, 
                 version: str, 
                 datetime: str, 
                 prompt_text: str, 
                 description: str, 
                 model: str, 
                 inputs: str | None = None, 
                 llm_result: str | None = None, 
                 nickname: str | None = None) -> None:
        super().__init__(version, datetime, prompt_text, description, model, inputs, llm_result, nickname)