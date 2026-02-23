import inspect
from typing import Any, Callable, Dict, Optional


class ToolRegistry:
    """简单的工具注册与调度器。

    使用 ``@register_tool(description="...")`` 装饰函数便可将其
    注册为可由智能体调用的 "工具"。注册器会保存函数本身、签名、
    文档字符串和额外的描述信息，便于自动生成给 LLM 的说明文档
    并在运行时根据名称调度调用。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, description: str = "") -> Callable:
        """装饰器：登记工具。

        ``description`` 会被包含在向 LLM 提供的提示文本中，用于说明
        该工具的用途。
        """

        def decorator(func: Callable) -> Callable:
            name = func.__name__
            sig = inspect.signature(func)
            doc = func.__doc__ or ""
            self._tools[name] = {
                "func": func,
                "description": description,
                "signature": sig,
                "doc": doc,
            }
            return func

        return decorator

    def get_prompt_description(self) -> str:
        """返回一段文本，列出所有注册的工具及其签名和说明。

        该文本适合直接拼入 system prompt 中，让 LLM 知道可用的工具。"""
        lines = []
        for name, info in self._tools.items():
            sig = info["signature"]
            doc = info["doc"].strip().replace("\n", " ")
            desc = info["description"].strip()
            # 保留参数类型提示以便 LLM 理解输入格式
            lines.append(f"- {name}{sig}: {doc} {desc}".strip())
        return "\n".join(lines)

    def dispatch_tool(self, name: str, args: Any = None, instance: Any = None) -> Any:
        """根据名称调用注册的工具。

        * ``name`` – 工具名，对应注册时的函数名。
        * ``args`` – 从 LLM 得到的 args，可以是 dict、字符串或 None。
        * ``instance`` – 若注册的是类的实例方法，应传入该实例，
          以便在调用前完成绑定。
        """
        info = self._tools.get(name)
        if info is None:
            raise KeyError(f"tool '{name}' not registered")

        fn = info["func"]
        if instance is not None:
            # 绑定到对象，否则顶级函数直接调用
            fn = fn.__get__(instance, instance.__class__)

        if args is None:
            return fn()
        if isinstance(args, dict):
            return fn(**args)
        # if args is a primitive value but the function takes no parameters,
        # ignore the argument to avoid crashes (common when LLM misuses tool).
        try:
            sig = info.get("signature")
            if sig is not None:
                # count parameters, subtract bound self if instance provided
                count = len(sig.parameters)
                if instance is not None and count > 0:
                    count -= 1
                if count == 0:
                    return fn()
        except Exception:
            pass
        # otherwise call with positional arg
        return fn(args)


# 全局单例便于其它模块直接引用
registry = ToolRegistry()
