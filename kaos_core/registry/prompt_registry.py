from __future__ import annotations

from kaos_core.base.prompt import KaosPrompt
from kaos_core.exceptions import RegistryError
from kaos_core.types.metadata import PromptMetadata


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, KaosPrompt] = {}

    def register_prompt(self, prompt: KaosPrompt) -> None:
        name = prompt.metadata.name
        if name in self._prompts:
            raise RegistryError("Prompt already registered", prompt_name=name)
        self._prompts[name] = prompt

    def get_prompt(self, name: str) -> KaosPrompt | None:
        return self._prompts.get(name)

    def list_prompts(self) -> list[str]:
        return sorted(self._prompts)

    def search_prompts(
        self, category: str | None = None, tags: list[str] | None = None
    ) -> list[PromptMetadata]:
        results: list[PromptMetadata] = []
        for prompt in self._prompts.values():
            metadata = prompt.metadata
            if category and metadata.category != category:
                continue
            if tags and not set(tags).issubset(metadata.tags):
                continue
            results.append(metadata)
        return results

    def get_stats(self) -> dict[str, int]:
        return {"prompts": len(self._prompts)}
