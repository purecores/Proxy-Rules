import subprocess
from pathlib import Path

# 固定配置
SINGBOX_EXE = Path(r"D:\APP\Sing-box\sing-box.exe")
PERSONALUSE_DIR = Path("./personaluse")

# 需要编译的 json 文件名
TARGET_JSON_FILES = [
    "personaluse-d.json",
    "personaluse-p.json",
]


def main():
    if not SINGBOX_EXE.exists():
        raise FileNotFoundError(f"sing-box.exe 不存在: {SINGBOX_EXE}")

    if not PERSONALUSE_DIR.exists():
        raise FileNotFoundError(f"personaluse 目录不存在: {PERSONALUSE_DIR}")

    for json_name in TARGET_JSON_FILES:
        json_file = PERSONALUSE_DIR / json_name

        if not json_file.exists():
            print(f"✘ 未找到文件: {json_file}")
            continue

        output_file = json_file.with_suffix(".srs")

        cmd = [
            str(SINGBOX_EXE),
            "rule-set",
            "compile",
            str(json_file),
            "-o",
            str(output_file),
        ]

        print(f"正在编译: {json_file.name}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            print(f"✔ 编译成功: {output_file.name}")
            if result.stdout:
                print(result.stdout)

        except subprocess.CalledProcessError as e:
            print(f"✘ 编译失败: {json_file.name}")
            if e.stderr:
                print(e.stderr)


if __name__ == "__main__":
    main()
