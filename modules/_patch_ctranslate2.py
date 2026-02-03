"""
modules/_patch_ctranslate2.py

修复 ctranslate2 在 Windows 上的 ROCm 路径问题，并添加 PyTorch CUDA 库路径。
这个模块必须在导入 faster_whisper 之前被导入。
"""

import os
import sys
from pathlib import Path

# 立即修补 os.add_dll_directory 以处理不存在的 ROCm 路径
_original_add_dll_directory = os.add_dll_directory

def _patched_add_dll_directory(path):
    """
    包装 os.add_dll_directory 以忽略不存在的 ROCm 路径和 CUDA 版本不匹配的路径。
    """
    if not path or not isinstance(path, str):
        return _original_add_dll_directory(path)
    
    # 过滤 ROCm 相关路径（ctranslate2 不需要 ROCm）
    if "rocm" in path.lower():
        print(f"[PATCH] 忽略 ROCm 路径: {path}")
        return None
    
    # 过滤不存在的路径
    if not os.path.exists(path):
        print(f"[PATCH] 忽略不存在的路径: {path}")
        return None
    
    # 如果路径有效，添加到 DLL 搜索路径
    try:
        return _original_add_dll_directory(path)
    except (FileNotFoundError, OSError) as e:
        print(f"[PATCH] 添加 DLL 目录失败: {path}, 错误: {e}")
        return None

# 立即应用补丁
os.add_dll_directory = _patched_add_dll_directory
print("[PATCH] ctranslate2 补丁已应用：os.add_dll_directory 已被修补")

# 添加 PyTorch CUDA 库路径，以解决 CUDA 版本不匹配的问题
# ctranslate2 可能在寻找 cublas64_12.dll，但 PyTorch CUDA 13 提供 cublas64_13.dll
# 将 PyTorch 的 lib 目录添加到 DLL 搜索路径使得库可被找到
try:
    import torch
    torch_lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(torch_lib_dir):
        try:
            _original_add_dll_directory(torch_lib_dir)
            print(f"[PATCH] 已添加 PyTorch CUDA 库路径: {torch_lib_dir}")
        except Exception as e:
            print(f"[PATCH] 添加 PyTorch 库路径失败: {e}")
except ImportError:
    print("[PATCH] PyTorch 未安装，跳过库路径添加")
