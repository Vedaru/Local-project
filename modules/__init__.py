"""Project modules package.

Keep package import lightweight and side-effect free.

Do not eagerly import heavy submodules (llm/voice/avatar) here,
so statements like `import modules._patch_ctranslate2` won't fail
because optional runtime dependencies are missing.
"""

__all__: list[str] = []
