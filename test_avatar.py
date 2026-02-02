"""
Avatar 模块测试脚本
用于测试 Live2D 模型加载和各种功能
"""
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from modules.avatar import AvatarWidget


def main():
    # 创建应用
    app = QApplication(sys.argv)
    
    # 创建 Avatar 窗口
    avatar = AvatarWidget(
        width=500,
        height=700,
        x=100,
        y=50
    )
    avatar.show()
    
    # 模型路径（相对于 assets/web/models/）
    # 修改这里为你的模型路径
    MODEL_PATH = "hiyori_free_en/runtime/hiyori_free_t08.model3.json"
    
    def on_ready():
        """页面就绪后加载模型"""
        print("\n[Test] 正在加载模型...")
        avatar.load_model(MODEL_PATH, on_model_loaded)
    
    def on_model_loaded(success: bool):
        """模型加载完成回调"""
        if success:
            print("[Test] ✓ 模型加载成功！")
            print("[Test] 提示：")
            print("  - 拖拽窗口可以移动位置")
            print("  - 双击窗口重置模型位置")
            print("  - 点击模型触发随机动作")
            print("  - 模型眼睛会跟随鼠标")
            
            # 测试各种功能
            QTimer.singleShot(2000, test_functions)
        else:
            print("[Test] ✗ 模型加载失败！")
    
    def test_functions():
        """测试各种功能"""
        print("\n[Test] 测试表情切换...")
        avatar.change_expression(0)
        
        QTimer.singleShot(1500, lambda: test_motion())
    
    def test_motion():
        """测试动作播放"""
        print("[Test] 测试动作播放...")
        avatar.play_motion("Idle")
        
        QTimer.singleShot(2000, lambda: test_lip_sync())
    
    def test_lip_sync():
        """测试口型同步"""
        print("[Test] 测试口型同步...")
        
        import math
        frame = [0]
        
        def animate_mouth():
            if frame[0] < 50:
                value = abs(math.sin(frame[0] * 0.3)) * 0.8
                avatar.update_lip_sync(value)
                frame[0] += 1
                QTimer.singleShot(50, animate_mouth)
            else:
                avatar.update_lip_sync(0)
                print("[Test] 口型同步测试完成")
                print("\n[Test] 所有测试完成！窗口将保持打开，可以继续交互。")
        
        animate_mouth()
    
    # 连接页面就绪信号
    avatar.page_ready.connect(on_ready)
    
    print("\n" + "="*50)
    print("  Live2D Avatar 测试程序")
    print("="*50)
    print(f"模型: {MODEL_PATH}")
    print("等待页面加载...\n")
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
