"""
一键打包 DeepHub MAX 为 Windows 可执行程序
=========================================
用法:  python build_exe.py

产物:  dist/DeepHub-MAX/DeepHub-MAX.exe  (onedir 模式，解压即运行)

依赖:  PyInstaller (pip install pyinstaller)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "DeepHub-MAX"


def main():
    # ─── 检查 PyInstaller ───
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("❌ 先装 PyInstaller: pip install pyinstaller")
        return 1

    # ─── 清理旧产物 ───
    for p in (DIST / NAME, BUILD / NAME, ROOT / f"{NAME}.spec"):
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
            print(f"  清理旧产物: {p}")

    # ─── PyInstaller 命令 ───
    # Windows 用分号分隔 add-data
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        # 入口点
        str(ROOT / "run.py"),
        # 打包配置
        "--onedir",                 # 一个文件夹，里面有 exe（解压即运行，不用每次解压 onefile）
        "--console",                # 有终端窗口（REPL 需要）
        f"--name={NAME}",
        f"--distpath={DIST}",
        f"--workpath={BUILD}",
        f"--specpath={ROOT}",
        "--noconfirm",              # 覆盖已存在的输出目录
        "--clean",                  # 清理 PyInstaller 缓存
        # 资源文件 (只读)
        f"--add-data=app/static{sep}app/static",
        f"--add-data=app/resources{sep}app/resources",
        # 内置插件模板（可写模式下拷到 %APPDATA%）
        f"--add-data=app/tools/plugins{sep}app/tools/plugins",
        # Flask 隐式依赖
        "--collect-all=flask",
        "--collect-all=werkzeug",
        # 动态 import 覆盖（plugin.py 的 exec / importlib）
        "--hidden-import=app.tools.plugin",
        "--hidden-import=app.tools.base",
        "--hidden-import=app.tools",
        # 入口路径
        "--paths", str(ROOT),
    ]

    print("🔧 PyInstaller 开始打包…")
    print(f"   {' '.join(cmd)}")
    print()

    # 跑
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n❌ PyInstaller 失败 (exit {result.returncode})")
        return result.returncode

    # ─── 验证产物 ───
    exe = DIST / NAME / f"{NAME}.exe"
    if not exe.exists():
        print(f"\n❌ 没找到 {exe}")
        return 1

    size_mb = exe.stat().st_size / 1024 / 1024
    total_files = sum(1 for _ in (DIST / NAME).rglob("*") if _.is_file())
    total_mb = sum(f.stat().st_size for f in (DIST / NAME).rglob("*") if f.is_file()) / 1024 / 1024

    print()
    print("═" * 60)
    print("✅ 打包完成！")
    print(f"  exe 路径: {exe}")
    print(f"  exe 体积: {size_mb:.1f} MB")
    print(f"  目录总大: {total_mb:.1f} MB  ({total_files} 个文件)")
    print()
    print("🚀 使用方式: 双击 exe 或 cmd 里直接运行")
    print("   插件自动落盘到 %APPDATA%/DeepHub-MAX/plugins/")
    print("═" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
