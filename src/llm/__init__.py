"""Abstraction LLM provider — permet de switcher entre Claude, Ollama, vLLM.

Point d'entrée : `get_llm()` (voir factory.py). Chaque service qui appelle un
LLM passe par le provider actif, jamais directement par le SDK Anthropic.

Décision produit : à moyen terme, Skilluv opère son propre stack IA. Court
terme : Claude API. Le switch se fait via env `SKILLUV_AI_LLM_PROVIDER`.
"""

from src.llm.base import LLMProvider, ModelTier
from src.llm.factory import get_llm

__all__ = ["LLMProvider", "ModelTier", "get_llm"]
