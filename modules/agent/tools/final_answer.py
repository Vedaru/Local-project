

def final_answer(agent_tools, content) -> str:
    """A trivial tool that returns a stringified value.

    This exists purely so that ``execute`` can delegate to a module
    rather than handling the case inline.
    """
    return str(content)
