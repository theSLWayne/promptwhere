"""
Entry point to the application
"""

class PromptWhere():
    def __init__(self) -> None:
        self.prompts: dict[str, str]

    def add_prompt(self, prompt_text: str, prompt_version: str):
        """
        To save a simple prompt in memory
        """

        self.prompts[prompt_version] = prompt_text

    def get_prompt_versions(self) -> list[str]:
        """
        To return the list of prompt versions
        """

        return list(self.prompts.keys())
    
    def get_prompt_from_version(self, prompt_version: str) -> str:
        """
        To return a specific prompt given by its version
        """

        prompt_text_received = self.prompts.get(prompt_version, None)

        if not prompt_text_received:
            raise ValueError(f"No prompt found for the given version {prompt_version}")
        
        return prompt_text_received