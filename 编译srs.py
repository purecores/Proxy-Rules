import subprocess
from pathlib import Path

# 固定配置
SINGBOX_EXE = Path(r"D:\APP\Sing-box\sing-box.exe")
JSON_DIR = Path("./singbox")


def main():
    if not SINGBOX_EXE.exists():
        raise FileNotFoundError(f"sing-box.exe 不存在: {SINGBOX_EXE}")

    if not JSON_DIR.exists():
        raise FileNotFoundError(f"JSON 规则集目录不存在: {JSON_DIR}")

    json_files = list(JSON_DIR.glob("*.json"))

    if not json_files:
        print("未找到任何 JSON 规则集文件")
        return

    for json_file in json_files:
        output_file = json_file.with_suffix(".srs")

        cmd = [
            str(SINGBOX_EXE),
            "rule-set",
            "compile",
            str(json_file),
            "-o",
            str(output_file)
        ]

        print(f"正在编译: {json_file.name}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
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
