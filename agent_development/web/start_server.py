#!/usr/bin/env python
"""
SCDB-Agent Web服务启动脚本
"""

import argparse
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def check_dependencies():
    """检查依赖是否安装"""
    try:
        import flask
        import flask_cors
        import flask_socketio
        print("✅ 依赖检查通过")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("\n请安装依赖:")
        print("  pip install -r web/requirements.txt")
        return False

def main():
    parser = argparse.ArgumentParser(description='SCDB-Agent Web服务')
    parser.add_argument('-p', '--port', type=int, default=5000, help='服务端口 (默认: 5000)')
    parser.add_argument('-H', '--host', type=str, default='0.0.0.0', help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('-d', '--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--no-reload', action='store_true', help='禁用自动重载')
    
    args = parser.parse_args()
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 导入应用
    try:
        from app import app, socketio, init_app
    except ImportError:
        # 尝试从web目录导入
        sys.path.insert(0, str(Path(__file__).parent))
        from app import app, socketio, init_app
    
    print("\n" + "=" * 60)
    print(" 🧬 SCDB-Agent Web 服务")
    print("=" * 60)
    print(f"\n服务地址: http://{args.host}:{args.port}")
    print(f"调试模式: {'启用' if args.debug else '禁用'}")
    print(f"自动重载: {'禁用' if args.no_reload else '启用'}")
    print("\n按 Ctrl+C 停止服务")
    print("=" * 60 + "\n")
    
    try:
        # 初始化应用
        init_app()
        
        # 启动服务
        socketio.run(
            app,
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_reloader=not args.no_reload and args.debug
        )
    except KeyboardInterrupt:
        print("\n\n👋 服务已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
