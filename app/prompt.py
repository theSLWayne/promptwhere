"""
Prompt Class is implemented here.
"""
from typing import Optional

class Prompt:
    def __init__(
            self, version: str, 
            datetime: str, prompt_text: str, 
            description: str, 
            inputs: Optional[str] = None, 
            llm_result: Optional[str] = None, 
            nickname: Optional[str] = None) -> None:
        
        self.version = version
        self.datetime = datetime
        self.prompt_text = prompt_text
        self. description = description
        self.inputs = inputs
        self.llm_result = llm_result
        self.nickname = nickname

    